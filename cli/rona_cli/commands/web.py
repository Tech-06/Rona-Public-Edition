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
import getpass
import json as jsonlib
import secrets
import shutil
import subprocess
import sys
from typing import Any

from rona_cli import envio, http, i18n, ui, webauth
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


def _warn_if_frontend_stale(data: dict[str, Any]) -> None:
    # web-client/webui/dist is gitignored: a `git pull` updates the frontend's
    # source but not the build every browser is actually served, so the new
    # UI silently never arrives. The dashboard itself detects that (see
    # webui/frontend_build.py); this is where the operator gets to hear it.
    if data.get("frontend_stale"):
        ui.warn(i18n.t("web.frontend_stale"))


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
        _warn_if_frontend_stale(describe(paths))
    return result.returncode


def _cmd_build(args: argparse.Namespace) -> int:
    """`rona web build` -- (re)compiles the frontend without touching a
    running panel's process. This is the piece a plain `git pull` never
    does on its own: web-client/webui/dist is gitignored (it's a build
    artifact, not source), so the panel keeps serving whatever it last
    compiled until this runs. Mirrors installer/steps/web.py's own
    npm ci/install + npm run build exactly, so a manual rebuild behaves
    the same way the installer's would.
    """
    paths = _resolve(args)
    if paths is None:
        return 1
    frontend_dir = paths.web_dir / "frontend"
    npm = shutil.which("npm")
    if npm is None:
        _fail(args, i18n.t("web.build_npm_not_found"))
        return 1

    on_windows = sys.platform == "win32"
    lockfile = frontend_dir / "package-lock.json"
    install_cmd = [npm, "ci"] if lockfile.exists() else [npm, "install"]
    if not args.json:
        ui.info(i18n.t("web.build_installing", cmd=" ".join(install_cmd)))
    result = subprocess.run(install_cmd, cwd=frontend_dir, check=False, shell=on_windows)
    if result.returncode != 0:
        _fail(args, i18n.t("web.build_install_failed"))
        return result.returncode

    if not args.json:
        ui.info(i18n.t("web.build_building"))
    result = subprocess.run([npm, "run", "build"], cwd=frontend_dir, check=False, shell=on_windows)
    if result.returncode != 0:
        _fail(args, i18n.t("web.build_failed"))
        return result.returncode

    if args.json:
        print(jsonlib.dumps({"ok": True}, ensure_ascii=False))
    else:
        ui.ok(i18n.t("web.build_done"))
        # A rebuild alone is enough for the *frontend* half of an upgrade --
        # a running panel picks up the new index.html on its own (see
        # webui/server.py's mtime-keyed cache). But `git pull` usually also
        # changed backend/ and web-client/webui/*.py, which only take
        # effect after their own processes restart.
        ui.info(i18n.t("web.build_restart_hint"))
    return 0


def _read_new_password(args: argparse.Namespace) -> str | None:
    """The new password from stdin (--stdin) or a hidden, confirmed prompt.

    Never from argv: a command-line value lands in shell history and in
    every other user's process list.
    """
    if args.stdin:
        return sys.stdin.readline().rstrip("\r\n")
    if not sys.stdin.isatty():
        _fail(args, i18n.t("web.password_needs_tty"))
        return None
    first = getpass.getpass(i18n.t("web.password_prompt"))
    if first != getpass.getpass(i18n.t("web.password_confirm_prompt")):
        _fail(args, i18n.t("web.password_mismatch"))
        return None
    return first


def _cmd_password(args: argparse.Namespace) -> int:
    """`rona web password` -- (re)sets the dashboard's login password.

    Writes WEB_PASSWORD_HASH plus a fresh WEB_SESSION_SECRET (so every
    existing browser session is signed out). The running dashboard re-reads
    web-client/.env on change, so no restart is needed.
    """
    paths = _resolve(args)
    if paths is None:
        return 1
    if not paths.web_env.is_file():
        _fail(args, i18n.t("web.password_not_installed"))
        return 1
    password = _read_new_password(args)
    if password is None:
        return 1
    if len(password) < webauth.MIN_PASSWORD_LENGTH:
        _fail(args, i18n.t("web.password_too_short", min=webauth.MIN_PASSWORD_LENGTH))
        return 1
    try:
        envio.write_env_updates(
            paths.web_env,
            {
                "WEB_PASSWORD_HASH": webauth.hash_password(password),
                "WEB_SESSION_SECRET": secrets.token_urlsafe(32),
            },
        )
    except (OSError, envio.EnvValueError) as exc:
        _fail(args, i18n.t("web.password_write_failed", error=exc))
        return 1
    if args.json:
        print(jsonlib.dumps({"ok": True}, ensure_ascii=False))
    else:
        ui.ok(i18n.t("web.password_set"))
    return 0


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
        _warn_if_frontend_stale(data)
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

    p_build = sub.add_parser("build", parents=[common], help=i18n.t("web.help_build"))
    p_build.set_defaults(func=_cmd_build)

    p_password = sub.add_parser("password", parents=[common], help=i18n.t("web.help_password"))
    p_password.add_argument(
        "--stdin", action="store_true", help=i18n.t("web.help_password_stdin")
    )
    p_password.set_defaults(func=_cmd_password)
