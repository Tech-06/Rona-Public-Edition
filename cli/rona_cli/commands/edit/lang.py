"""`rona edit lang` -- show or set the language of all three Rona
components: the backend's `LANGUAGE` (backend/.env), the web dashboard's
`UI_LANGUAGE` (web-client/.env), and this CLI's own language, stored in
~/.rona/config.json's "language" (the same file rona_cli.paths.state_file
already points at, and the same one the installer writes -- see the
language plan's "Ortak sözleşme" table for why each lives where it does).

With no `language` argument, shows the current setting of all three.
With one, sets it -- all three by default, or only the ones named by
--backend/--web/--cli.
"""

from __future__ import annotations

import argparse
import json as jsonlib

from rona_cli import envio, i18n, ui
from rona_cli.paths import RonaNotFoundError, RonaPaths, find_root, state_file


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


def _read_cli_language() -> str:
    path = state_file()
    if not path.is_file():
        return i18n.DEFAULT_LANGUAGE
    try:
        data = jsonlib.loads(path.read_text(encoding="utf-8"))
    except (OSError, jsonlib.JSONDecodeError):
        return i18n.DEFAULT_LANGUAGE
    lang = data.get("language")
    return lang if lang in i18n.SUPPORTED else i18n.DEFAULT_LANGUAGE


def _write_cli_language(lang: str) -> None:
    """Merges into ~/.rona/config.json rather than overwriting it --
    installer.state.write_state's other fields (root, components,
    installed_at, platform) must survive this."""
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if path.is_file():
        try:
            data = jsonlib.loads(path.read_text(encoding="utf-8"))
        except (OSError, jsonlib.JSONDecodeError):
            data = {}
    data["language"] = lang
    path.write_text(jsonlib.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _cmd_show(args: argparse.Namespace) -> int:
    paths = _resolve(args)
    if paths is None:
        return 1
    backend_lang = envio.read_env_file(paths.backend_env).get("LANGUAGE", "") or i18n.DEFAULT_LANGUAGE
    web_lang = envio.read_env_file(paths.web_env).get("UI_LANGUAGE", "") or i18n.DEFAULT_LANGUAGE
    cli_lang = _read_cli_language()
    if args.json:
        print(
            jsonlib.dumps(
                {"ok": True, "backend": backend_lang, "web": web_lang, "cli": cli_lang},
                ensure_ascii=False,
            )
        )
        return 0
    ui.info(i18n.t("lang.current_backend", lang=backend_lang))
    ui.info(i18n.t("lang.current_web", lang=web_lang))
    ui.info(i18n.t("lang.current_cli", lang=cli_lang))
    return 0


def _cmd_set(args: argparse.Namespace) -> int:
    # No target flags given at all -> set all three (mirrors `rona edit
    # auth reset`/`set`, which always write both .env files).
    any_target = args.backend or args.web or args.cli
    do_backend = args.backend or not any_target
    do_web = args.web or not any_target
    do_cli = args.cli or not any_target

    changed: list[str] = []

    if do_backend or do_web:
        paths = _resolve(args)
        if paths is None:
            return 1
        if do_backend:
            envio.write_env_updates(paths.backend_env, {"LANGUAGE": args.language})
            changed.append("backend")
        if do_web:
            envio.write_env_updates(paths.web_env, {"UI_LANGUAGE": args.language})
            changed.append("web")

    if do_cli:
        _write_cli_language(args.language)
        changed.append("cli")

    if args.json:
        print(
            jsonlib.dumps(
                {"ok": True, "language": args.language, "changed": changed}, ensure_ascii=False
            )
        )
    else:
        ui.ok(i18n.t("lang.set_ok", language=args.language, changed=", ".join(changed)))
        if "backend" in changed or "web" in changed:
            ui.info(i18n.t("lang.restart_hint"))
    return 0


def _dispatch(args: argparse.Namespace) -> int:
    if args.language is None:
        return _cmd_show(args)
    return _cmd_set(args)


def register(subparsers, common) -> None:
    parser = subparsers.add_parser("lang", parents=[common], help=i18n.t("lang.help_group"))
    parser.add_argument(
        "language", nargs="?", choices=i18n.SUPPORTED, default=None, help=i18n.t("lang.help_language_arg")
    )
    parser.add_argument("--backend", action="store_true", help=i18n.t("lang.help_backend_flag"))
    parser.add_argument("--web", action="store_true", help=i18n.t("lang.help_web_flag"))
    parser.add_argument("--cli", action="store_true", help=i18n.t("lang.help_cli_flag"))
    parser.set_defaults(func=_dispatch)
