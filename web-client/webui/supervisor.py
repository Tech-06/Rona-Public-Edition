import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from webui.config import get_settings

settings = get_settings()

ROOT_DIR = Path(__file__).resolve().parent.parent
LOCK_PATH = ROOT_DIR / "webui.lock"
LOG_PATH = ROOT_DIR / "webui.log"

STARTUP_TIMEOUT_SECONDS = 15
POLL_INTERVAL_SECONDS = 0.5


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _probe_host(host: str) -> str:
    """Address to dial for a server bound to ``host`` (wildcards -> loopback)."""
    host = (host or "").strip()
    if host in ("", "0.0.0.0", "::", "[::]"):
        return "127.0.0.1"
    return host


def _probe_host_header() -> str:
    """A Host value TrustedHostMiddleware accepts: the first allowed host
    (skipping wildcard patterns), else localhost."""
    for entry in settings.web_allowed_hosts.split(","):
        entry = entry.strip()
        if entry and "*" not in entry:
            return entry
    return "localhost"


def is_running() -> dict[str, Any] | None:
    probe_host = _probe_host(settings.web_host)
    if not _port_open(probe_host, settings.web_port):
        return None
    try:
        # TrustedHostMiddleware rejects "Host: 0.0.0.0", so send an allowed host
        # instead (localhost may not be in WEB_ALLOWED_HOSTS).
        response = httpx.get(
            f"http://{probe_host}:{settings.web_port}/host/healthz",
            headers={"Host": _probe_host_header()},
            timeout=1.0,
        )
        data = response.json()
    except Exception:  # noqa: BLE001
        return None
    if data.get("service") != "rona-web":
        return None
    return data


def start() -> bool:
    running = is_running()
    if running is not None:
        print(f"rona-web already running (pid {running.get('pid')})")
        return True
    try:
        lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print("Another process is already starting rona-web")
        return False
    try:
        kwargs: dict[str, Any] = {"cwd": ROOT_DIR}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.DETACHED_PROCESS
        else:
            kwargs["start_new_session"] = True
        # The child inherits its own copy of the handle; close ours afterwards.
        with LOG_PATH.open("a", encoding="utf-8") as log_file:
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "webui.server:app",
                    "--host",
                    settings.web_host,
                    "--port",
                    str(settings.web_port),
                ],
                stdout=log_file,
                stderr=log_file,
                **kwargs,
            )
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if is_running() is not None:
                print(f"rona-web started on {settings.web_host}:{settings.web_port}")
                return True
            time.sleep(POLL_INTERVAL_SECONDS)
        print("rona-web did not report healthy within the startup timeout")
        return False
    finally:
        os.close(lock_fd)
        try:
            LOCK_PATH.unlink()
        except OSError:
            pass


def stop() -> bool:
    running = is_running()
    if running is None:
        print("rona-web is not running")
        return True
    pid = running.get("pid")
    if pid is None:
        print("rona-web is running but reported no pid")
        return False
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=False)
    else:
        os.kill(pid, 15)
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if is_running() is None:
            print("rona-web stopped")
            return True
        time.sleep(POLL_INTERVAL_SECONDS)
    print("rona-web did not stop within the timeout")
    return False


def restart() -> bool:
    stop()
    return start()


def status() -> None:
    running = is_running()
    if running is None:
        print("rona-web is not running")
        return
    print(
        f"rona-web is running (pid {running.get('pid')}, "
        f"uptime {running.get('uptime_seconds')}s)"
    )
