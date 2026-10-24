"""Cross-platform helpers for spawning, tracking, and killing a detached
background process (used to run the backend without a systemd unit).

Mirrors the patterns already used by ``web-client/webui/supervisor.py`` and
``web-client/webui/host.py`` for the backend, so the CLI's own supervision
behaves the same way the web dashboard's does.
"""

from __future__ import annotations

import csv
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path


def port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def spawn_detached(cmd: list[str], cwd: Path, log_path: Path) -> subprocess.Popen:
    kwargs: dict = {"cwd": cwd}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    # The child inherits its own copy of the handle; close ours afterwards.
    with log_path.open("a", encoding="utf-8") as log_file:
        return subprocess.Popen(cmd, stdout=log_file, stderr=log_file, **kwargs)


def _tasklist_has_pid(output: str, pid: int) -> bool:
    """True if a ``tasklist /FO CSV /NH`` row's PID column equals ``pid``.

    A substring test would let pid 12 match a row for pid 1234 (or a memory
    figure), so the CSV row is parsed and the PID column compared exactly.
    The "INFO: No tasks are running..." line is not a CSV row and never matches.
    """
    for row in csv.reader(output.splitlines()):
        if len(row) >= 2 and row[1].strip() == str(pid):
            return True
    return False


def pid_alive(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        return _tasklist_has_pid(result.stdout, pid)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True  # exists, just owned by someone else
    except OSError:
        return False
    return True


def _signal_tree(pid: int, sig: int) -> None:
    """Signal ``pid``'s whole process group, but only if it leads one.

    The backend is started with ``start_new_session=True``, so its pid is its
    own group id. A process we did not start (found via the port lookup) may
    share a group with a shell or other services; ``killpg`` on that would
    take them down too, so then only the single pid is signalled.
    """
    try:
        if os.getpgid(pid) == pid:
            os.killpg(pid, sig)
        else:
            os.kill(pid, sig)
    except ProcessLookupError:
        pass


def kill_tree(pid: int) -> None:
    """Kill the process and (best-effort) everything it spawned.

    A backend running with ``RELOAD=true`` (dev setups) has uvicorn's
    reload watcher process plus its own worker child -- killing only the pid
    we tracked would leave the worker running. On Windows ``taskkill /T``
    kills the whole tree; on POSIX see ``_signal_tree``.
    """
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False
        )
        return
    _signal_tree(pid, signal.SIGTERM)


def force_kill(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False
        )
        return
    _signal_tree(pid, signal.SIGKILL)


def _netstat_listener_pid(output: str, port: int) -> int | None:
    """PID of the first TCP listener whose local port is exactly ``port``.

    The state column is localized ("LISTENING", "DINLENIYOR", "ABHÖREN"...),
    so a listener is recognised by its foreign address instead: a listening
    socket has no peer (``0.0.0.0:0``, ``[::]:0``, ``*:*``).
    """
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        if parts[2].rpartition(":")[2] not in ("0", "*"):
            continue
        if parts[1].rpartition(":")[2] == str(port):
            try:
                return int(parts[-1])
            except ValueError:
                continue
    return None


def find_pid_by_port(host: str, port: int) -> int | None:
    """Best-effort lookup of the pid *listening* on ``port``.

    Used as a fallback when there's no pid file (e.g. the backend was
    started outside of ``rona``) so ``rona server stop`` can still work.
    Only the listening socket counts: plain ``lsof tcp:PORT`` also lists
    clients connected to the port, which are unrelated processes.
    """
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=5, check=False
            )
            return _netstat_listener_pid(result.stdout, port)
        result = subprocess.run(
            ["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        output = result.stdout.strip()
        if output:
            return int(output.splitlines()[0])
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return None


class VerifyError(Exception):
    """The process could not be inspected (tool missing, permission denied)."""


def _read_proc_cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError as exc:
        raise VerifyError(str(exc)) from exc
    return raw.replace(b"\0", b" ").decode("utf-8", errors="replace").strip()


def _read_proc_cwd(pid: int) -> str | None:
    try:
        return str(Path(f"/proc/{pid}/cwd").resolve(strict=True))
    except OSError:
        return None


def _run_text(cmd: list[str]) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise VerifyError(str(exc)) from exc
    if result.returncode != 0:
        raise VerifyError((result.stderr or "").strip() or f"exit code {result.returncode}")
    return result.stdout.strip()


def _macos_cwd(pid: int) -> str | None:
    """Best effort: the cwd is only a second signal next to the command line."""
    try:
        out = _run_text(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"])
    except VerifyError:
        return None
    for line in out.splitlines():
        if line.startswith("n"):
            return line[1:]
    return None


def _windows_cmdline(pid: int) -> str:
    try:
        return _run_text(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine",
            ]
        )
    except VerifyError:
        pass  # no powershell (or it failed): try the legacy tool
    out = _run_text(
        ["wmic", "process", "where", f"ProcessId={int(pid)}", "get", "CommandLine", "/value"]
    )
    return out.partition("=")[2].strip()


def _fold(path: str) -> str:
    return path.replace("\\", "/").rstrip("/").lower()


def _looks_like_backend(cmdline: str, cwd: str | None, backend_dir: Path) -> bool:
    lowered = cmdline.lower()
    if not ("run.py" in lowered or ("uvicorn" in lowered and "app.main" in lowered)):
        return False
    target = _fold(str(backend_dir))
    if cwd is not None and _fold(cwd) == target:
        return True
    # Started from elsewhere: the script path or the backend venv's python
    # in the command line still ties it to this checkout's backend.
    return target in _fold(cmdline)


def is_rona_backend(pid: int, backend_dir: Path) -> bool:
    """Whether ``pid`` is this checkout's backend (``run.py`` / ``uvicorn app.main``).

    Killing whatever happens to sit on port 8000, or whatever a stale pid file
    names (pids get reused), could take down an unrelated program. Returns
    False when the process cannot be inspected: not killing is the safe side.
    """
    try:
        if sys.platform == "win32":
            cmdline, cwd = _windows_cmdline(pid), None
        elif sys.platform.startswith("linux"):
            cmdline, cwd = _read_proc_cmdline(pid), _read_proc_cwd(pid)
        else:
            cmdline = _run_text(["ps", "-o", "command=", "-p", str(pid)])
            cwd = _macos_cwd(pid)
    except VerifyError:
        return False
    return _looks_like_backend(cmdline, cwd, backend_dir)


def write_pid_file(path: Path, pid: int) -> None:
    path.write_text(str(pid), encoding="utf-8")


def read_pid_file(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def clear_pid_file(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def tail_lines(path: Path, count: int, block_size: int = 8192) -> list[str]:
    """Last ``count`` lines of ``path``, read backwards in blocks (logs reach 10 MB)."""
    if count <= 0:
        return []
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            data = b""
            # Need count + 1 newlines so the earliest wanted line is complete.
            while position > 0 and data.count(b"\n") <= count:
                read_size = min(block_size, position)
                position -= read_size
                handle.seek(position)
                data = handle.read(read_size) + data
    except OSError:
        return []
    text = data.decode("utf-8", errors="replace")
    lines = [line.rstrip("\r") for line in text.split("\n")]
    if lines and lines[-1] == "":
        lines.pop()
    if position > 0 and len(lines) > count:
        lines = lines[1:]
    return lines[-count:]
