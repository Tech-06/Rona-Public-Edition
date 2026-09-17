import asyncio
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from webui import db, proxy
from webui.config import get_settings

settings = get_settings()
logger = logging.getLogger("uvicorn.error")
router = APIRouter(prefix="/host")

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = (ROOT_DIR / settings.backend_dir).resolve()
LOG_PATH = BACKEND_DIR / settings.backend_log_file
SPAWN_LOG_PATH = BACKEND_DIR / "backend_spawn.log"

STARTED_AT = time.time()
RESTART_MIN_INTERVAL_SECONDS = 10

_backend_process: subprocess.Popen | None = None
_last_restart_at = 0.0


def _systemctl_available() -> bool:
    return shutil.which("systemctl") is not None and sys.platform != "win32"


def _run_systemctl(action: str) -> dict[str, Any]:
    result = subprocess.run(
        ["systemctl", "--user", action, "rona"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return {"ok": result.returncode == 0, "detail": (result.stdout + result.stderr).strip()}


async def _spawn_backend() -> dict[str, Any]:
    global _backend_process
    if not BACKEND_DIR.is_dir():
        return {"ok": False, "detail": f"Backend directory not found: {BACKEND_DIR}"}
    if _backend_process is not None and _backend_process.poll() is None:
        return {"ok": False, "detail": "Backend already tracked as running"}
    log_file = SPAWN_LOG_PATH.open("a", encoding="utf-8")
    kwargs: dict[str, Any] = {"cwd": BACKEND_DIR, "stdout": log_file, "stderr": log_file}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    _backend_process = subprocess.Popen([sys.executable, "run.py"], **kwargs)  # noqa: ASYNC220
    await asyncio.sleep(1.5)
    if _backend_process.poll() is not None:
        detail = f"Backend exited immediately (code {_backend_process.returncode})"
        detail += "; " + "; ".join(_tail_lines(SPAWN_LOG_PATH, 5))
        _backend_process = None
        return {"ok": False, "detail": detail}
    return {"ok": True, "detail": f"Started PID {_backend_process.pid}"}


def _kill_backend() -> dict[str, Any]:
    global _backend_process
    if _backend_process is None or _backend_process.poll() is not None:
        return {"ok": False, "detail": "No backend process tracked by this web server"}
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(_backend_process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    else:
        _backend_process.terminate()
    _backend_process = None
    return {"ok": True, "detail": "Stop requested"}


def _tail_lines(path: Path, count: int) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    return [line.rstrip("\n") for line in lines[-count:]]


@router.get("/healthz")
async def web_healthz():
    return {
        "service": "rona-web",
        "pid": os.getpid(),
        "uptime_seconds": round(time.time() - STARTED_AT, 2),
    }


@router.get("/server")
async def server_status():
    health = await proxy.backend_health()
    tracked_alive = _backend_process is not None and _backend_process.poll() is None
    return {
        "backend_up": health["up"],
        "backend_detail": health["detail"],
        "tracked_process_alive": tracked_alive,
        "tracked_pid": _backend_process.pid if tracked_alive else None,
        "systemctl_available": _systemctl_available(),
        "recent_log_lines": _tail_lines(LOG_PATH, 50),
    }


def _check_restart_rate_limit() -> None:
    global _last_restart_at
    now = time.monotonic()
    if now - _last_restart_at < RESTART_MIN_INTERVAL_SECONDS:
        raise HTTPException(429, "Restart requested too soon; wait a few seconds")
    _last_restart_at = now


@router.post("/server/start")
async def server_start(request: Request):
    _check_restart_rate_limit()
    logger.info("[host] start requested by %s", request.client.host if request.client else "?")
    if _systemctl_available():
        return _run_systemctl("start")
    return await _spawn_backend()


@router.post("/server/stop")
async def server_stop(request: Request):
    _check_restart_rate_limit()
    logger.info("[host] stop requested by %s", request.client.host if request.client else "?")
    if _systemctl_available():
        return _run_systemctl("stop")
    return _kill_backend()


@router.post("/server/restart")
async def server_restart(request: Request):
    _check_restart_rate_limit()
    logger.info("[host] restart requested by %s", request.client.host if request.client else "?")
    if _systemctl_available():
        return _run_systemctl("restart")
    _kill_backend()
    await asyncio.sleep(1.0)
    return await _spawn_backend()


@router.get("/db/tasks")
async def degraded_tasks():
    connection = db.connect_if_exists()
    if connection is None:
        return {"degraded": True, "tasks": []}
    cursor = connection.cursor()
    cursor.execute(
        "SELECT id, name, status, is_recurring, cron_expression, scheduled_at, "
        "timezone, created_at FROM tasks ORDER BY created_at DESC LIMIT 100"
    )
    rows = [dict(row) for row in cursor.fetchall()]
    connection.close()
    return {"degraded": True, "tasks": rows}


@router.get("/db/subagents")
async def degraded_subagents():
    connection = db.connect_if_exists()
    if connection is None:
        return {"degraded": True, "runs": []}
    cursor = connection.cursor()
    cursor.execute(
        "SELECT id, task, tier, status, created_at, finished_at FROM subagent_runs "
        "ORDER BY created_at DESC LIMIT 50"
    )
    rows = [dict(row) for row in cursor.fetchall()]
    connection.close()
    return {"degraded": True, "runs": rows}
