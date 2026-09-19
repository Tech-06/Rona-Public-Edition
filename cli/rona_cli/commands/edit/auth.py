"""`rona edit auth get|reset|set` -- manage the shared AUTH_TOKEN that both
backend/.env and web-client/.env must hold identically (see
app/main.py's bearer-token check and webui/proxy.py, which injects it into
every proxied request)."""

from __future__ import annotations

import argparse
import json as jsonlib
import secrets

from rona_cli import envio, ui
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
        return "(boş)"
    if len(token) <= 4:
        return "*" * len(token)
    return f"{'*' * (len(token) - 4)}{token[-4:]}"


def _write_both(paths: RonaPaths, token: str) -> None:
    envio.write_env_updates(paths.backend_env, {"AUTH_TOKEN": token})
    envio.write_env_updates(paths.web_env, {"AUTH_TOKEN": token})


def _restart_hint() -> None:
    ui.info("Değişikliğin geçmesi için `rona server restart` ve `rona web restart` çalıştır.")


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
        confirmed = ui.confirm(
            "Yeni bir AUTH_TOKEN üretilip backend ve web .env dosyalarına yazılsın mı? "
            "Çalışan süreçlerin yeniden başlatılması gerekir.",
            default=False,
        )
        if not confirmed:
            ui.info("Vazgeçildi.")
            return 1
    token = secrets.token_urlsafe(TOKEN_BYTES)
    _write_both(paths, token)
    if args.json:
        print(jsonlib.dumps({"ok": True, "token": token}, ensure_ascii=False))
    else:
        ui.ok("Yeni AUTH_TOKEN backend ve web .env dosyalarına yazıldı.")
        _restart_hint()
    return 0


def _cmd_set(args: argparse.Namespace) -> int:
    paths = _resolve(args)
    if paths is None:
        return 1
    token = args.token.strip()
    if not token:
        _emit_error(args, "token boş olamaz")
        return 1
    _write_both(paths, token)
    if args.json:
        print(jsonlib.dumps({"ok": True}, ensure_ascii=False))
    else:
        ui.ok("AUTH_TOKEN backend ve web .env dosyalarına yazıldı.")
        _restart_hint()
    return 0


def register(subparsers, common) -> None:
    parser = subparsers.add_parser("auth", parents=[common], help="Paylaşılan AUTH_TOKEN'ı yönet")
    sub = parser.add_subparsers(dest="auth_command", required=True)

    p_get = sub.add_parser("get", parents=[common], help="Mevcut token'ı göster")
    p_get.add_argument("--show", action="store_true", help="token'ı maskelemeden göster")
    p_get.set_defaults(func=_cmd_get)

    p_reset = sub.add_parser("reset", parents=[common], help="Yeni rastgele bir token üret")
    p_reset.add_argument("--yes", action="store_true", help="onay sorma")
    p_reset.set_defaults(func=_cmd_reset)

    p_set = sub.add_parser("set", parents=[common], help="Belirli bir token'ı ayarla")
    p_set.add_argument("token")
    p_set.set_defaults(func=_cmd_set)
