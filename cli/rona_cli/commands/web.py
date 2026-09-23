"""`rona web` -- start/stop/restart/status for the web dashboard (port 8016).

Process supervision (lock file, health polling, pid tracking) is already
implemented in ``web-client/webui/supervisor.py`` -- this module doesn't
reimplement it. It locates the web-client's own venv python and shells out
to ``python -m webui <action>`` (inheriting stdio, so the user sees that
module's own messages live), and reports status via the same
``/host/healthz`` endpoint that module already polls internally.
"""

from __future__ import annotations

import argparse
import json as jsonlib
import subprocess
from typing import Any

from rona_cli import envio, http, i18n, ui
from rona_cli.paths import RonaNotFoundError, RonaPaths, find_root


def describe(paths: RonaPaths) -> dict[str, Any]:
    env = envio.read_env_file(paths.web_env)
    host = env.get("WEB_HOST", "127.0.0.1") or "127.0.0.1"
    try:
        port = int(env.get("WEB_PORT", "8016") or "8016")
    except ValueError:
        port = 8016
    client = http.Client(base_url=f"http://{host}:{port}", timeout=3.0)
    try:
        data = client.get("/host/healthz")
    except http.ApiError as exc:
        return {"running": False, "host": host, "port": port, "detail": str(exc)}
    data.update({"running": True, "host": host, "port": port})
    return data


def _resolve(args: argparse.Namespace) -> RonaPaths | None:
    try:
        return RonaPaths(find_root(args.root))
    except RonaNotFoundError as exc:
        _fail(args, str(exc))
        return None


def _fail(args: argparse.Namespace, message: str) -> None:
    if args.json:
        print(jsonlib.dumps({"ok": False, "error": message}, ensure_ascii=False))
    else:
        ui.error(message)


def _warn_if_frontend_stale(paths: RonaPaths, data: dict[str, Any]) -> None:
    # web-client/webui/dist is gitignored: a `git pull` updates the frontend's
    # source but not the build every browser is actually served, so the new
    # UI silently never arrives. The dashboard itself detects that (see
    # webui/frontend_build.py); this is where the operator gets to hear it.
    if data.get("frontend_stale"):
        ui.warn(i18n.t("web.frontend_stale", path=paths.web_dir / "frontend"))


def _delegate(args: argparse.Namespace, action: str) -> int:
    paths = _resolve(args)
    if paths is None:
        return 1
    try:
        python = paths.web_python()
    except RonaNotFoundError as exc:
        _fail(args, str(exc))
        return 1
    result = subprocess.run([str(python), "-m", "webui", action], cwd=paths.web_dir, check=False)
    if args.json:
        print(
            jsonlib.dumps(
                {"ok": result.returncode == 0, "action": action, "web": describe(paths)},
                ensure_ascii=False,
            )
        )
    elif action != "stop" and result.returncode == 0:
        _warn_if_frontend_stale(paths, describe(paths))
    return result.returncode


def _cmd_start(args: argparse.Namespace) -> int:
    return _delegate(args, "start")


def _cmd_stop(args: argparse.Namespace) -> int:
    return _delegate(args, "stop")


def _cmd_restart(args: argparse.Namespace) -> int:
    return _delegate(args, "restart")


def _cmd_status(args: argparse.Namespace) -> int:
    paths = _resolve(args)
    if paths is None:
        return 1
    data = describe(paths)
    if args.json:
        print(jsonlib.dumps({"ok": True, "web": data}, ensure_ascii=False))
        return 0
    if data.get("running"):
        ui.ok(
            i18n.t(
                "web.status_running",
                host=data["host"],
                port=data["port"],
                pid=data.get("pid"),
                uptime=data.get("uptime_seconds", "?"),
            )
        )
        _warn_if_frontend_stale(paths, data)
    else:
        ui.warn(i18n.t("web.status_stopped", detail=data.get("detail", "")))
    return 0


def register(subparsers, common) -> None:
    parser = subparsers.add_parser("web", parents=[common], help=i18n.t("web.help_group"))
    sub = parser.add_subparsers(dest="web_command", required=True)

    p_start = sub.add_parser("start", parents=[common], help=i18n.t("web.help_start"))
    p_start.set_defaults(func=_cmd_start)

    p_stop = sub.add_parser("stop", parents=[common], help=i18n.t("web.help_stop"))
    p_stop.set_defaults(func=_cmd_stop)

    p_restart = sub.add_parser("restart", parents=[common], help=i18n.t("web.help_restart"))
    p_restart.set_defaults(func=_cmd_restart)

    p_status = sub.add_parser("status", parents=[common], help=i18n.t("web.help_status"))
    p_status.set_defaults(func=_cmd_status)
