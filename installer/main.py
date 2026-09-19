"""Rona installer -- cross-platform, stdlib-only.

Bootstrapped by install.ps1 (Windows) / install.sh (macOS, Linux), which
only ensure a Python 3.11+ interpreter is on PATH before handing off here.
Everything else lives in this package: component selection, Node
prerequisites, venvs, .env generation, and the npm build.
"""

from __future__ import annotations

import argparse
import io
import json as jsonlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _path in (str(REPO_ROOT), str(REPO_ROOT / "cli")):
    if _path not in sys.path:
        sys.path.insert(0, _path)


def _ensure_utf8_streams() -> None:
    """Force UTF-8 stdout/stderr so Turkish text doesn't crash on a plain
    Windows console (whose default codepage, e.g. cp1252, can't encode it).
    Mirrors cli/rona_cli/cli.py's own fix for the same problem.
    """
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            try:
                stream.reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass

from rona_cli import envio

from installer import detect, envgen, i18n, pathsetup, prereq, state, ui, wizard
from installer.steps import backend as backend_step
from installer.steps import cli as cli_step
from installer.steps import web as web_step

MIN_PYTHON = (3, 11)
MIN_NODE_MAJOR = 18
_COMPONENTS = ("cli", "backend", "web")


def _labels() -> dict[str, str]:
    # A function, not a module constant, for the same reason wizard.py's
    # field dicts are: the language for this run isn't known at import
    # time, only after main() asks/resolves it.
    return {
        "cli": i18n.t("main.label_cli"),
        "backend": i18n.t("main.label_backend"),
        "web": i18n.t("main.label_web"),
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    # These help=/description= strings stay in Turkish, not t(...): argparse
    # resolves --help (and any parse error) *during* parse_args(), which
    # runs before main() has asked/resolved a language -- there's no
    # language to translate into yet. Every other user-facing string in
    # this package runs after that point and does go through t(...).
    parser = argparse.ArgumentParser(prog="installer", description="Rona kurulum aracı")
    parser.add_argument("--yes", action="store_true", help="hiç sormadan devam et")
    parser.add_argument(
        "--components",
        default=None,
        help="virgülle ayrılmış bileşen listesi (cli,backend,web); "
        "verilmezse seçim menüsü gösterilir",
    )
    parser.add_argument(
        "--repair", action="store_true", help="sadece zaten kurulu olan bileşenleri onar"
    )
    parser.add_argument("--json", action="store_true", help="sonucu JSON olarak ver")
    parser.add_argument(
        "--lang",
        choices=i18n.SUPPORTED,
        default=None,
        help="kurulum dili (verilmezse ve --yes/--json de verilmemişse sorulur; "
        "yoksa varsayılan tr)",
    )
    return parser.parse_args(argv)


def _select_components(args: argparse.Namespace, installed: detect.InstalledComponents) -> list[str] | None:
    installed_dict = installed.as_dict()

    if args.repair:
        selected = [name for name in _COMPONENTS if installed_dict[name]]
        if not selected:
            ui.error(i18n.t("main.repair_none_found"))
            return None
        return selected

    if args.components:
        requested = {c.strip() for c in args.components.split(",") if c.strip()}
        unknown = requested - set(_COMPONENTS)
        if unknown:
            ui.error(i18n.t("main.unknown_components", names=", ".join(sorted(unknown))))
            return None
        return [c for c in _COMPONENTS if c in requested]

    if args.yes or args.json:
        return list(_COMPONENTS)

    labels = _labels()
    options = [
        (name, labels[name], True, i18n.t("main.status_reinstall") if installed_dict[name] else "")
        for name in _COMPONENTS
    ]
    return ui.select_components(options)


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_streams()
    args = _parse_args(argv)

    # Language, before anything else runs: explicit --lang wins outright;
    # otherwise --yes/--json (non-interactive automation) silently defaults
    # to tr rather than blocking on a prompt; otherwise ask -- in both
    # languages at once, since none is chosen yet (see i18n.ask_language).
    if args.lang:
        i18n.set_language(args.lang)
    elif args.yes or args.json:
        i18n.set_language(i18n.DEFAULT_LANGUAGE)
    else:
        i18n.set_language(i18n.ask_language())

    ui.step(i18n.t("main.step_precheck"))
    py_version = detect.python_version()
    if py_version < MIN_PYTHON:
        ui.error(
            i18n.t(
                "main.python_too_old",
                min_major=MIN_PYTHON[0],
                min_minor=MIN_PYTHON[1],
                found_major=py_version[0],
                found_minor=py_version[1],
            )
        )
        return 1
    ui.ok(f"Python {py_version[0]}.{py_version[1]}.{py_version[2]}")

    if not detect.git_available():
        ui.warn(i18n.t("main.git_not_found"))

    os_name = detect.detect_os()
    pkg_manager = detect.package_manager(os_name)
    installed = detect.InstalledComponents(REPO_ROOT)

    selected = _select_components(args, installed)
    if not selected:
        if selected is not None:
            ui.warn(i18n.t("main.no_components_selected"))
        return 1

    if "web" in selected:
        node = detect.node_version()
        if node is None or node[0] < MIN_NODE_MAJOR:
            if not prereq.ensure_prerequisite("Node.js", "node", False, os_name, pkg_manager, args.yes):
                ui.error(i18n.t("main.node_required"))
                return 1
        else:
            ui.ok(f"Node.js {node[0]}.{node[1]}.{node[2]}")

    installed_dict = installed.as_dict()
    results: dict[str, bool] = {}
    if "cli" in selected:
        results["cli"] = cli_step.install(REPO_ROOT, reinstall=installed_dict["cli"])
        if results["cli"]:
            pathsetup.setup(REPO_ROOT / "cli" / ".venv", auto_yes=args.yes or args.json)
    if "backend" in selected:
        results["backend"] = backend_step.install(REPO_ROOT, reinstall=installed_dict["backend"])
    if "web" in selected:
        results["web"] = web_step.install(REPO_ROOT, reinstall=installed_dict["web"])

    backend_env_path = REPO_ROOT / "backend" / ".env"
    web_env_path = REPO_ROOT / "web-client" / ".env"
    if backend_env_path.exists():
        envgen.ensure_auth_token(REPO_ROOT, install_web="web" in selected)
        ui.ok(i18n.t("main.auth_token_set"))
    # The language just chosen (or --lang) becomes each installed
    # component's own default too, so it keeps speaking it without needing
    # `rona edit lang` afterward -- only touches a component that's
    # actually part of this run.
    envgen.ensure_language(
        REPO_ROOT,
        i18n.get_language(),
        install_backend=backend_env_path.exists(),
        install_web=web_env_path.exists(),
    )

    all_ok = bool(results) and all(results.values())

    interactive = not args.yes and not args.json
    if interactive and results.get("backend"):
        wizard.run(REPO_ROOT, backend_in_scope=True)

    if all_ok:
        state.write_state(
            REPO_ROOT,
            {name: (name in selected) for name in _COMPONENTS},
            language=i18n.get_language(),
        )

    ui.step(i18n.t("main.step_summary"))
    for name, succeeded in results.items():
        status = i18n.t("main.status_done" if succeeded else "main.status_failed")
        (ui.ok if succeeded else ui.error)(i18n.t("main.result_line", name=name, status=status))

    if all_ok:
        ui.info("")
        ui.info(i18n.t("main.next_steps_heading"))
        if "backend" in selected:
            flash_configured = bool(envio.read_env_file(backend_env_path).get("FLASH_MODEL"))
            if not flash_configured:
                ui.info(i18n.t("main.next_step_model"))
            ui.info("  rona server start")
        if "web" in selected:
            ui.info("  rona web start")

    if args.json:
        print(jsonlib.dumps({"ok": all_ok, "results": results}, ensure_ascii=False))

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
