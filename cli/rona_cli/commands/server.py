"""`rona server` -- start/stop/restart/status for the backend (port 8000).

Unlike the web dashboard, the backend has no supervisor of its own (no pid
file, no lock, no stop command) -- this module is what adds that. It prefers
a systemd user unit when one is available (same detection as
``web-client/webui/host.py``), and otherwise spawns/tracks the process
itself via ``rona_cli.procutil``.
"""

from __future__ import annotations

import argparse
import json as jsonlib
import os
import shutil
import subprocess
import time
from typing import Any

from rona_cli import envio, http, procutil, ui
from rona_cli.paths import RonaNotFoundError, RonaPaths, find_root

START_TIMEOUT_SECONDS = 25
STOP_TIMEOUT_SECONDS = 20
POLL_INTERVAL_SECONDS = 0.5
EARLY_EXIT_CHECK_SECONDS = 1.5


def _env_host_port(env: dict[str, str]) -> tuple[str, int]:
    host = env.get("HOST", "0.0.0.0") or "0.0.0.0"
    if host in ("0.0.0.0", ""):
        host = "127.0.0.1"
    try:
        port = int(env.get("PORT", "8000") or "8000")
    except ValueError:
        port = 8000
    return host, port


def _client(paths: RonaPaths) -> tuple[http.Client, str, int, bool]:
    env = envio.read_env_file(paths.backend_env)
    host, port = _env_host_port(env)
    token = env.get("AUTH_TOKEN", "")
    return (
        http.Client(base_url=f"http://{host}:{port}", token=token, timeout=2.0),
        host,
        port,
        bool(token),
    )


def _healthy(client: http.Client, host: str, port: int, have_token: bool) -> bool:
    # /health requires a bearer token (it sits behind main.py's global auth
    # dependency), so without one we can only confirm the port is open, not
    # that the app actually started -- Settings() itself requires AUTH_TOKEN
    # and FLASH_MODEL*, so an incomplete .env makes uvicorn crash on boot,
    # a difference a plain port check cannot see.
    if have_token:
        try:
            client.get("/health")
            return True
        except http.ApiError:
            return False
    return procutil.port_open(host, port)


def _systemctl_available() -> bool:
    return shutil.which("systemctl") is not None and os.name != "nt"


def _run_systemctl(action: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["systemctl", "--user", action, "rona"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def describe(paths: RonaPaths) -> dict[str, Any]:
    client, host, port, have_token = _client(paths)
    if not have_token:
        return {
            "running": False,
            "host": host,
            "port": port,
            "detail": "AUTH_TOKEN ayarlanmamış",
        }
    try:
        data = client.get("/api/status")
    except http.ApiError as exc:
        return {"running": False, "host": host, "port": port, "detail": str(exc)}
    data.update({"running": True, "host": host, "port": port})
    return data


def _start(paths: RonaPaths) -> tuple[bool, str]:
    client, host, port, have_token = _client(paths)
    if _healthy(client, host, port, have_token):
        return True, "backend zaten çalışıyor"

    if _systemctl_available():
        started, detail = _run_systemctl("start")
        if not started:
            return False, detail or "systemctl start başarısız oldu"
    else:
        python = paths.backend_python()
        log_path = paths.backend_dir / "backend_spawn.log"
        proc = procutil.spawn_detached(
            [str(python), "run.py"], cwd=paths.backend_dir, log_path=log_path
        )
        procutil.write_pid_file(paths.backend_pid, proc.pid)
        time.sleep(EARLY_EXIT_CHECK_SECONDS)
        if proc.poll() is not None:
            procutil.clear_pid_file(paths.backend_pid)
            tail = "; ".join(procutil.tail_lines(log_path, 5))
            return False, f"backend hemen sonlandı (çıkış kodu {proc.returncode}); {tail}"

    deadline = time.monotonic() + START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _healthy(client, host, port, have_token):
            return True, f"backend {host}:{port} adresinde başlatıldı"
        time.sleep(POLL_INTERVAL_SECONDS)
    return False, "backend zaman aşımı içinde sağlıklı duruma gelmedi (`rona log tail` ile kontrol et)"


def _stop(paths: RonaPaths) -> tuple[bool, str]:
    client, host, port, have_token = _client(paths)
    if not _healthy(client, host, port, have_token) and not procutil.port_open(host, port):
        procutil.clear_pid_file(paths.backend_pid)
        return True, "backend zaten çalışmıyor"

    if _systemctl_available():
        stopped, detail = _run_systemctl("stop")
        if not stopped:
            return False, detail or "systemctl stop başarısız oldu"
    else:
        pid = procutil.read_pid_file(paths.backend_pid)
        if pid is None or not procutil.pid_alive(pid):
            pid = procutil.find_pid_by_port(host, port)
        if pid is None:
            return False, (
                "durdurulacak süreç bulunamadı (pid dosyası yok); backend rona "
                "dışında başlatılmış olabilir, elle durdurman gerekir"
            )
        procutil.kill_tree(pid)

    procutil.clear_pid_file(paths.backend_pid)
    deadline = time.monotonic() + STOP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if not procutil.port_open(host, port):
            return True, "backend durduruldu"
        time.sleep(POLL_INTERVAL_SECONDS)
    return False, "backend zaman aşımı içinde durmadı"


def _restart(paths: RonaPaths) -> tuple[bool, str]:
    _, stop_detail = _stop(paths)
    start_ok, start_detail = _start(paths)
    return start_ok, start_detail if start_ok else f"{stop_detail}; {start_detail}"


def _resolve(args: argparse.Namespace) -> RonaPaths | None:
    try:
        return RonaPaths(find_root(args.root))
    except RonaNotFoundError as exc:
        _emit_error(args, str(exc))
        return None


def _emit_error(args: argparse.Namespace, message: str) -> None:
    if args.json:
        print(jsonlib.dumps({"ok": False, "error": message}, ensure_ascii=False))
    else:
        ui.error(message)


def _emit_result(args: argparse.Namespace, action: str, succeeded: bool, detail: str) -> int:
    if args.json:
        print(
            jsonlib.dumps(
                {"ok": succeeded, "action": action, "detail": detail}, ensure_ascii=False
            )
        )
    elif succeeded:
        ui.ok(detail)
    else:
        ui.error(detail)
    return 0 if succeeded else 1


def _cmd_start(args: argparse.Namespace) -> int:
    paths = _resolve(args)
    if paths is None:
        return 1
    succeeded, detail = _start(paths)
    return _emit_result(args, "start", succeeded, detail)


def _cmd_stop(args: argparse.Namespace) -> int:
    paths = _resolve(args)
    if paths is None:
        return 1
    succeeded, detail = _stop(paths)
    return _emit_result(args, "stop", succeeded, detail)


def _cmd_restart(args: argparse.Namespace) -> int:
    paths = _resolve(args)
    if paths is None:
        return 1
    succeeded, detail = _restart(paths)
    return _emit_result(args, "restart", succeeded, detail)


def _cmd_status(args: argparse.Namespace) -> int:
    paths = _resolve(args)
    if paths is None:
        return 1
    data = describe(paths)
    if args.json:
        print(jsonlib.dumps({"ok": True, "backend": data}, ensure_ascii=False))
        return 0
    if data.get("running"):
        ui.ok(
            f"Backend {data['host']}:{data['port']} adresinde çalışıyor "
            f"(uptime {data.get('uptime_seconds', '?')}s, model {data.get('flash_model', '?')})"
        )
        ui.info(
            f"         pro model: {'yapılandırıldı' if data.get('pro_configured') else 'yok'}, "
            f"zamanlayıcı: {'çalışıyor' if data.get('scheduler_running') else 'kapalı'}"
        )
    else:
        ui.warn(f"Backend çalışmıyor ({data.get('detail', '')})")
    return 0


def register(subparsers, common) -> None:
    parser = subparsers.add_parser("server", parents=[common], help="Backend sürecini yönet")
    sub = parser.add_subparsers(dest="server_command", required=True)

    p_start = sub.add_parser("start", parents=[common], help="Backend sürecini başlat")
    p_start.set_defaults(func=_cmd_start)

    p_stop = sub.add_parser("stop", parents=[common], help="Backend sürecini durdur")
    p_stop.set_defaults(func=_cmd_stop)

    p_restart = sub.add_parser("restart", parents=[common], help="Backend sürecini yeniden başlat")
    p_restart.set_defaults(func=_cmd_restart)

    p_status = sub.add_parser("status", parents=[common], help="Backend sürecinin durumunu göster")
    p_status.set_defaults(func=_cmd_status)
