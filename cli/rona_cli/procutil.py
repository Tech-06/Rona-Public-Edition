"""Cross-platform helpers for spawning, tracking, and killing a detached
background process (used to run the backend without a systemd unit).

Mirrors the patterns already used by ``web-client/webui/supervisor.py`` and
``web-client/webui/host.py`` for the backend, so the CLI's own supervision
behaves the same way the web dashboard's does.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
from pathlib import Path


def port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def spawn_detached(cmd: list[str], cwd: Path, log_path: Path) -> subprocess.Popen:
    log_file = log_path.open("a", encoding="utf-8")
    kwargs: dict = {"cwd": cwd, "stdout": log_file, "stderr": log_file}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def pid_alive(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def kill_tree(pid: int) -> None:
    """Kill the process and (best-effort) everything it spawned.

    Backends run with ``RELOAD=true`` by default, which means uvicorn's
    reload watcher process has its own worker child -- killing only the pid
    we tracked would leave the worker running. On Windows ``taskkill /T``
    kills the whole tree; on POSIX we launched with a new session
    (``start_new_session=True``), so the pid is also the process group id.
    """
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False
        )
        return
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def force_kill(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False
        )
        return
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def find_pid_by_port(host: str, port: int) -> int | None:
    """Best-effort lookup of the pid listening on ``port``.

    Used as a fallback when there's no pid file (e.g. the backend was
    started outside of ``rona``) so ``rona server stop`` can still work.
    """
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=5, check=False
            )
            for line in result.stdout.splitlines():
                parts = line.split()
                if (
                    len(parts) >= 5
                    and parts[0].upper() == "TCP"
                    and parts[1].endswith(f":{port}")
                    and "LISTENING" in line.upper()
                ):
                    return int(parts[-1])
        else:
            result = subprocess.run(
                ["lsof", "-ti", f"tcp:{port}"],
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


def tail_lines(path: Path, count: int) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    return [line.rstrip("\n") for line in lines[-count:]]
