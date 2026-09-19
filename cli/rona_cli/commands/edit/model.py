"""`rona edit model flash|pro|embedding` -- view/edit the model tiers stored
in the backend's own .env, and optionally verify them with a real API call
before writing (`--test`).
"""

from __future__ import annotations

import argparse
import json as jsonlib

from rona_cli import envio, providers, ui
from rona_cli.paths import RonaNotFoundError, RonaPaths, find_root

_TARGETS = {
    "flash": {
        "name": "FLASH_MODEL",
        "url": "FLASH_MODEL_URL",
        "key": "FLASH_MODEL_API",
        "headers": "FLASH_MODEL_HEADERS",
    },
    "pro": {
        "name": "PRO_MODEL",
        "url": "PRO_MODEL_URL",
        "key": "PRO_MODEL_API",
        "headers": "PRO_MODEL_HEADERS",
    },
    "embedding": {
        "name": "EMBEDDING_MODEL_NAME",
        "key": "GOOGLE_API_KEY",
    },
}


def _mask(value: str) -> str:
    if not value:
        return "(boş)"
    if len(value) <= 4:
        return "*" * len(value)
    return f"{'*' * (len(value) - 4)}{value[-4:]}"


def _current_values(env: dict[str, str], field_map: dict[str, str]) -> dict[str, str]:
    return {field: env.get(env_key, "") for field, env_key in field_map.items()}


def _prompt_for_missing(
    target: str,
    field_map: dict[str, str],
    current: dict[str, str],
    given: dict[str, str | None],
) -> dict[str, str]:
    """Interactive fallback when no --name/--url/--key/--headers were passed
    at all: show current values, let the user keep or replace each one."""
    result = dict(current)
    ui.heading(f"{target} model ayarları")
    for field in field_map:
        if given.get(field) is not None:
            result[field] = given[field]
            continue
        shown = _mask(current[field]) if field == "key" else (current[field] or "(boş)")
        raw = input(f"  {field} [{shown}] (boş bırak = değiştirme): ").strip()
        if raw:
            result[field] = raw
    return result


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


def _run_test(target: str, values: dict[str, str]) -> tuple[bool, str]:
    if target == "embedding":
        return providers.test_embedding(values.get("key", ""), values.get("name", ""))
    try:
        headers = providers.parse_headers(values.get("headers"))
    except ValueError as exc:
        return False, str(exc)
    return providers.test_chat_model(
        values.get("url", ""), values.get("key", ""), values.get("name", ""), headers
    )


def _cmd(args: argparse.Namespace) -> int:
    paths = _resolve(args)
    if paths is None:
        return 1

    field_map = _TARGETS[args.target]
    if args.target == "embedding" and not args.json:
        for ignored in ("url", "headers"):
            if getattr(args, ignored, None) is not None:
                ui.warn(f"embedding hedefi için --{ignored} yok sayıldı")

    env = envio.read_env_file(paths.backend_env)
    current = _current_values(env, field_map)

    given = {"name": args.name, "url": args.url, "key": args.key, "headers": args.headers}
    given = {k: v for k, v in given.items() if k in field_map}

    if any(v is not None for v in given.values()) or args.json:
        values = dict(current)
        values.update({field: value for field, value in given.items() if value is not None})
    else:
        values = _prompt_for_missing(args.target, field_map, current, given)

    if args.test:
        ok, detail = _run_test(args.target, values)
        if not ok:
            if args.json or not ui.confirm(
                f"Test başarısız oldu ({detail}). Yine de kaydedilsin mi?", default=False
            ):
                _emit_error(args, f"test başarısız: {detail}")
                return 1
        elif not args.json:
            ui.ok("Test başarılı.")

    updates: dict[str, str] = {}
    for field, env_key in field_map.items():
        if field == "headers":
            try:
                parsed = providers.parse_headers(values.get(field))
            except ValueError as exc:
                _emit_error(args, str(exc))
                return 1
            updates[env_key] = jsonlib.dumps(parsed, ensure_ascii=False)
        else:
            updates[env_key] = values.get(field, "")
    envio.write_env_updates(paths.backend_env, updates)

    if args.json:
        print(jsonlib.dumps({"ok": True, "target": args.target}, ensure_ascii=False))
    else:
        ui.ok(
            f"{args.target} ayarları kaydedildi. Geçmesi için "
            "`rona server restart` çalıştır."
        )
    return 0


def register(subparsers, common) -> None:
    parser = subparsers.add_parser(
        "model", parents=[common], help="Flash/Pro/embedding model ayarlarını düzenle"
    )
    parser.add_argument("target", choices=sorted(_TARGETS), help="düzenlenecek model katmanı")
    parser.add_argument("--name", default=None, help="model adı")
    parser.add_argument("--url", default=None, help="API taban URL'si (flash/pro)")
    parser.add_argument("--key", default=None, help="API anahtarı")
    parser.add_argument("--headers", default=None, help="ek HTTP başlıkları (JSON, flash/pro)")
    parser.add_argument(
        "--test", action="store_true", help="kaydetmeden önce gerçek bir API çağrısıyla doğrula"
    )
    parser.set_defaults(func=_cmd)
