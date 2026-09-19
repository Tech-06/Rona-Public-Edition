"""`rona edit auth get|reset|set` -- manage the shared AUTH_TOKEN that both
backend/.env and web-client/.env must hold identically (see
app/main.py's bearer-token check and webui/proxy.py, which injects it into
every proxied request)."""

from __future__ import annotations

import argparse
import json as jsonlib
import secrets

from rona_cli import envio, i18n, ui
from rona_cli.paths import RonaNotFoundError, RonaPaths, find_root

TOKEN_BYTES = 32


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


def _mask(token: str) -> str:
    if not token:
        return i18n.t("common.empty")
    if len(token) <= 4:
        return "*" * len(token)
    return f"{'*' * (len(token) - 4)}{token[-4:]}"


def _write_both(paths: RonaPaths, token: str) -> None:
    envio.write_env_updates(paths.backend_env, {"AUTH_TOKEN": token})
    envio.write_env_updates(paths.web_env, {"AUTH_TOKEN": token})


def _restart_hint() -> None:
    ui.info(i18n.t("auth.restart_hint"))


def _cmd_get(args: argparse.Namespace) -> int:
    paths = _resolve(args)
    if paths is None:
        return 1
    token = envio.read_env_file(paths.backend_env).get("AUTH_TOKEN", "")
    shown = token if args.show else _mask(token)
    if args.json:
        print(jsonlib.dumps({"ok": True, "token": shown}, ensure_ascii=False))
    else:
        ui.info(shown)
    return 0


def _cmd_reset(args: argparse.Namespace) -> int:
    paths = _resolve(args)
    if paths is None:
        return 1
    if not args.yes and not args.json:
        confirmed = ui.confirm(i18n.t("auth.confirm_reset"), default=False)
        if not confirmed:
            ui.info(i18n.t("common.cancelled"))
            return 1
    token = secrets.token_urlsafe(TOKEN_BYTES)
    _write_both(paths, token)
    if args.json:
        print(jsonlib.dumps({"ok": True, "token": token}, ensure_ascii=False))
    else:
        ui.ok(i18n.t("auth.reset_ok"))
        _restart_hint()
    return 0


def _cmd_set(args: argparse.Namespace) -> int:
    paths = _resolve(args)
    if paths is None:
        return 1
    token = args.token.strip()
    if not token:
        _emit_error(args, i18n.t("auth.empty_token"))
        return 1
    _write_both(paths, token)
    if args.json:
        print(jsonlib.dumps({"ok": True}, ensure_ascii=False))
    else:
        ui.ok(i18n.t("auth.set_ok"))
        _restart_hint()
    return 0


def register(subparsers, common) -> None:
    parser = subparsers.add_parser("auth", parents=[common], help=i18n.t("auth.help_group"))
    sub = parser.add_subparsers(dest="auth_command", required=True)

    p_get = sub.add_parser("get", parents=[common], help=i18n.t("auth.help_get"))
    p_get.add_argument("--show", action="store_true", help=i18n.t("auth.help_show_flag"))
    p_get.set_defaults(func=_cmd_get)

    p_reset = sub.add_parser("reset", parents=[common], help=i18n.t("auth.help_reset"))
    p_reset.add_argument("--yes", action="store_true", help=i18n.t("common.help_skip_confirm"))
    p_reset.set_defaults(func=_cmd_reset)

    p_set = sub.add_parser("set", parents=[common], help=i18n.t("auth.help_set"))
    p_set.add_argument("token")
    p_set.set_defaults(func=_cmd_set)
