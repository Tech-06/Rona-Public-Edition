"""Install/update/uninstall custom toolbox packages from the web dashboard.

Mirrors what `rona tools install/update/uninstall` already does from a
terminal (see cli/rona_cli/commands/tools.py's `_run_captured`), but the
caller here is an HTTP request instead of a live terminal, and the backend
process cannot run this itself: the BFF's read timeout to the backend is 45s while pip/git
can run for minutes, and RELOAD=true means the backend may restart itself
mid-install and lose any in-process job state.

So this module shells out to `backend/.venv`'s own
``python -m toolbox.manager --json ...`` as a detached subprocess whose
combined stdout+stderr goes to a log *file* rather than a pipe (so a BFF
restart never breaks a running install), and tracks progress in memory
(module-level ``_job``) by polling ``Popen.poll()`` -- never
``os.kill(pid, 0)``, which sends a real signal on POSIX and is simply wrong
on Windows. There is at most one job at a time; `toolbox.manager`'s own
file lock (`toolbox/custom/.manager.lock`) is what actually prevents a
concurrent CLI-side install from racing this one, but rejecting a second
web-side job early (409) gives a much better error message than waiting on
a lock that manager.py's rollback logic could hold for a while.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from webui import host, i18n

router = APIRouter(prefix="/host/packages")

PACKAGE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

# How long a single `available`/`plan` query may block for.
QUERY_TIMEOUT_SECONDS = 150
# How long a cached `available` result is served before the next call
# re-queries the manager -- installing/updating already invalidates it
# early (see _invalidate_available_cache), this is only the passive TTL.
AVAILABLE_CACHE_SECONDS = 300
# A runaway install/update/uninstall subprocess is killed after this long
# rather than left running forever if pip or git hangs.
JOB_MAX_SECONDS = 1800
LOG_TAIL_LINES = 300
LOG_LINE_MAX_CHARS = 2000


class ManagerUnavailable(Exception):
    """The backend's own venv interpreter doesn't exist yet (never set up,
    or `.venv` deleted). ``path`` is the interpreter path that was missing,
    for the error message."""

    def __init__(self, path: str):
        super().__init__(path)
        self.path = path


class ManagerFailed(Exception):
    """The manager subprocess ran but produced nothing usable: it timed out,
    or neither stdout nor stderr contained a parseable JSON result line."""


class PackageJobBusy(Exception):
    pass


def _expected_backend_python() -> Path:
    return (
        host.BACKEND_DIR / ".venv" / "Scripts" / "python.exe"
        if sys.platform == "win32"
        else host.BACKEND_DIR / ".venv" / "bin" / "python"
    )


def manager_command(*args: str) -> list[str]:
    """The full ``[python, -m, toolbox.manager, --json, *args]`` argv.

    A single choke point so tests can monkeypatch this one function to
    point at a fake script instead of a real backend venv + toolbox.
    """
    python = host.backend_python()
    if python is None:
        raise ManagerUnavailable(str(_expected_backend_python()))
    return [str(python), "-m", "toolbox.manager", "--json", *args]


def _subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _popen_kwargs() -> dict[str, Any]:
    # DETACHED_PROCESS (used by host.py for the backend itself) opens a
    # visible console window for git/pip's own child processes on Windows;
    # CREATE_NO_WINDOW avoids that without detaching the process group.
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {"start_new_session": True}


def _now() -> float:
    # Epoch seconds -- what the frontend's PackageJob type expects.
    return time.time()


def _parse_json_line(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line:
        return None
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) and "ok" in payload else None


def _last_json_result(text: str) -> dict[str, Any] | None:
    """The manager's own result line: the last line of ``text`` that parses
    as a JSON object with an ``"ok"`` key. Progress lines (``[toolbox] ...``)
    never parse as JSON, so this naturally skips them without needing the
    prefix convention here at all."""
    for line in reversed(text.splitlines()):
        payload = _parse_json_line(line)
        if payload is not None:
            return payload
    return None


def run_manager_query(*args: str, timeout: float = QUERY_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Run a read-only manager command (``available``, ``plan <id>``) to
    completion and return its JSON result. Blocking -- callers use
    ``asyncio.to_thread``."""
    cmd = manager_command(*args)
    try:
        result = subprocess.run(
            cmd,
            cwd=host.BACKEND_DIR,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env=_subprocess_env(),
            timeout=timeout,
            check=False,
            **_popen_kwargs(),
        )
    except subprocess.TimeoutExpired as exc:
        raise ManagerFailed(i18n.t("webui.manager_timeout")) from exc
    payload = _last_json_result(result.stdout)
    if payload is None:
        tail = "\n".join(result.stderr.strip().splitlines()[-LOG_TAIL_LINES:])
        raise ManagerFailed(tail or i18n.t("webui.manager_no_output"))
    return payload


def _kill_process_tree(process: subprocess.Popen) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, 15)  # SIGTERM; POSIX only, see module docstring
    with contextlib.suppress(Exception):
        process.wait(timeout=5)


@dataclass
class PackageJob:
    id: str
    action: str
    package_id: str
    started_at: float
    started_monotonic: float
    log_path: Path
    process: subprocess.Popen
    finished_at: float | None = None
    returncode: int | None = None
    result: dict[str, Any] | None = None
    error: str | None = None

    def _finish(self, *, result: dict[str, Any] | None = None, error: str | None = None) -> None:
        self.result = result
        self.error = error
        self.finished_at = _now()
        _invalidate_available_cache()

    def refresh(self) -> None:
        """Check on the subprocess and settle this job's state if it's done
        (or has overrun ``JOB_MAX_SECONDS``). A no-op once already finished."""
        if self.finished_at is not None:
            return
        if time.monotonic() - self.started_monotonic > JOB_MAX_SECONDS:
            _kill_process_tree(self.process)
            self.returncode = self.process.poll()
            self._finish(error=i18n.t("webui.package_job_timed_out"))
            return
        returncode = self.process.poll()
        if returncode is None:
            return
        self.returncode = returncode
        text = (
            self.log_path.read_text(encoding="utf-8", errors="replace")
            if self.log_path.exists()
            else ""
        )
        payload = _last_json_result(text)
        if payload is not None and payload.get("ok") and returncode == 0:
            self._finish(result=payload)
        elif payload is not None:
            self._finish(error=payload.get("error") or i18n.t("webui.manager_no_output"))
        else:
            tail = "\n".join(text.strip().splitlines()[-LOG_TAIL_LINES:])
            self._finish(error=tail or i18n.t("webui.manager_no_output"))

    @property
    def state(self) -> str:
        if self.finished_at is None:
            return "running"
        return "succeeded" if self.result is not None else "failed"

    def _log_lines(self) -> list[str]:
        if not self.log_path.exists():
            return []
        text = self.log_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        # The manager's own final JSON result line is machine-readable
        # noise for a human reading the log -- `result`/`error` above
        # already surface it structured.
        if lines and _parse_json_line(lines[-1]) is not None:
            lines = lines[:-1]
        return [line[:LOG_LINE_MAX_CHARS] for line in lines[-LOG_TAIL_LINES:]]

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "package_id": self.package_id,
            "state": self.state,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "log_lines": self._log_lines(),
            "result": self.result,
            "error": self.error,
        }


_job_lock = threading.Lock()
_job: PackageJob | None = None

_available_cache_lock = threading.Lock()
_available_cache: tuple[float, dict[str, Any]] | None = None


def _invalidate_available_cache() -> None:
    global _available_cache
    with _available_cache_lock:
        _available_cache = None


def start_job(action: str, package_id: str, manager_args: list[str]) -> PackageJob:
    """Start one install/update/uninstall job, or raise if one is already
    running. Blocking (spawns a subprocess) -- callers use
    ``asyncio.to_thread``."""
    global _job
    with _job_lock:
        if _job is not None:
            _job.refresh()
            if _job.state == "running":
                raise PackageJobBusy(i18n.t("webui.package_job_busy"))
            with contextlib.suppress(OSError):
                _job.log_path.unlink()
        cmd = manager_command(*manager_args)
        fd, log_path_str = tempfile.mkstemp(prefix="rona-package-job-", suffix=".log")
        log_path = Path(log_path_str)
        log_file = os.fdopen(fd, "wb")
        try:
            process = subprocess.Popen(  # noqa: ASYNC220 -- deliberately sync, see module docstring
                cmd,
                cwd=host.BACKEND_DIR,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=_subprocess_env(),
                **_popen_kwargs(),
            )
        finally:
            # The child inherited its own duplicated handle to the file; the
            # BFF's must close now, or a Windows file lock on the log file
            # would fight this process's own later reads of it (and a BFF
            # restart mid-install with the handle still open would be worse).
            log_file.close()
        job = PackageJob(
            id=uuid.uuid4().hex[:12],
            action=action,
            package_id=package_id,
            started_at=_now(),
            started_monotonic=time.monotonic(),
            log_path=log_path,
            process=process,
        )
        _job = job
        return job


def _validate_package_id(package_id: str) -> None:
    if not PACKAGE_ID_RE.match(package_id):
        raise HTTPException(400, i18n.t("webui.invalid_package_id", package_id=package_id))


class PackageIdPayload(BaseModel):
    package_id: str


class UninstallPayload(BaseModel):
    package_id: str
    purge: bool = False


@router.get("/available")
async def get_available(refresh: bool = False):
    global _available_cache
    if not refresh:
        with _available_cache_lock:
            if (
                _available_cache is not None
                and time.monotonic() - _available_cache[0] < AVAILABLE_CACHE_SECONDS
            ):
                return _available_cache[1]
    try:
        payload = await asyncio.to_thread(run_manager_query, "available")
    except ManagerUnavailable as exc:
        raise HTTPException(503, i18n.t("webui.backend_python_missing", path=exc.path)) from exc
    except ManagerFailed as exc:
        raise HTTPException(502, str(exc)) from exc
    if not payload.get("ok"):
        raise HTTPException(502, payload.get("error") or i18n.t("webui.manager_no_output"))
    body = {**payload, "fetched_at": _now()}
    with _available_cache_lock:
        _available_cache = (time.monotonic(), body)
    return body


@router.get("/plan/{package_id}")
async def get_plan(package_id: str):
    _validate_package_id(package_id)
    try:
        payload = await asyncio.to_thread(run_manager_query, "plan", package_id)
    except ManagerUnavailable as exc:
        raise HTTPException(503, i18n.t("webui.backend_python_missing", path=exc.path)) from exc
    except ManagerFailed as exc:
        raise HTTPException(502, str(exc)) from exc
    if not payload.get("ok"):
        raise HTTPException(409, payload.get("error") or i18n.t("webui.manager_no_output"))
    return payload


def _start_job_or_error(action: str, package_id: str, manager_args: list[str]) -> PackageJob:
    try:
        return start_job(action, package_id, manager_args)
    except PackageJobBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    except ManagerUnavailable as exc:
        raise HTTPException(503, i18n.t("webui.backend_python_missing", path=exc.path)) from exc


@router.post("/install", status_code=202)
async def post_install(payload: PackageIdPayload):
    _validate_package_id(payload.package_id)
    manager_args = [
        "install",
        payload.package_id,
        "--yes",
        "--defer-config",
        "--keep-on-health-failure",
    ]
    job = await asyncio.to_thread(_start_job_or_error, "install", payload.package_id, manager_args)
    return {"job": job.to_json()}


@router.post("/update", status_code=202)
async def post_update(payload: PackageIdPayload):
    _validate_package_id(payload.package_id)
    manager_args = ["update", payload.package_id, "--yes", "--defer-config"]
    job = await asyncio.to_thread(_start_job_or_error, "update", payload.package_id, manager_args)
    return {"job": job.to_json()}


@router.post("/uninstall", status_code=202)
async def post_uninstall(payload: UninstallPayload):
    _validate_package_id(payload.package_id)
    # --force is never passed from the web -- a dependent that would break
    # is something the panel should show and let the person decide about,
    # not something a background HTTP call silently overrides.
    manager_args = ["uninstall", payload.package_id, "--yes"]
    if payload.purge:
        manager_args.append("--purge")
    job = await asyncio.to_thread(
        _start_job_or_error, "uninstall", payload.package_id, manager_args
    )
    return {"job": job.to_json()}


@router.get("/job")
async def get_job():
    job = _job
    if job is not None:
        await asyncio.to_thread(job.refresh)
    return {"job": job.to_json() if job is not None else None}
