"""Rona uninstaller -- cross-platform, stdlib-only.

Bootstrapped by uninstall.ps1 (Windows) / uninstall.sh (macOS, Linux),
mirroring install.ps1/install.sh's own bootstrap exactly (ensure a
Python 3.11+ interpreter is on PATH, then hand off here).

Detects what a previous install actually left on disk and lets the user
pick exactly what to remove -- nothing is pre-checked (opt-in only, not
opt-out), and the repo checkout itself is never deleted, only what the
installer created inside it (and, for PATH, outside it).

The language question asked here (see i18n.ask_language()) affects only
this script's own output. It is never saved anywhere and never changes
an installed component's own language (backend LANGUAGE, web
UI_LANGUAGE, or the CLI's ~/.rona/config.json "language") -- the user's
explicit ask.
"""

from __future__ import annotations

import argparse
import io
import json as jsonlib
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _path in (str(REPO_ROOT), str(REPO_ROOT / "cli")):
    if _path not in sys.path:
        sys.path.insert(0, _path)


def _ensure_utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            try:
                stream.reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


from rona_cli import procutil

from installer import i18n, pathsetup, state, ui

_ITEMS = ("environments", "path", "state", "user-data", "tool-packages", "runtime")


def _label_key(item: str) -> str:
    return f"uninstall.item_{item.replace('-', '_')}"


def _custom_package_paths(root: Path) -> list[Path]:
    custom_dir = root / "backend" / "toolbox" / "custom"
    if not custom_dir.is_dir():
        return []
    return [
        p
        for p in custom_dir.iterdir()
        if p.name not in ("__init__.py", ".gitkeep", "__pycache__", "installed.json")
    ]


def _path_shim_exists() -> bool:
    if sys.platform == "win32":
        return (pathsetup._windows_bin_dir() / "rona.cmd").is_file()
    return (pathsetup._posix_bin_dir() / "rona").is_file()


def _detect(root: Path) -> dict[str, bool]:
    backend_dir = root / "backend"
    web_dir = root / "web-client"
    return {
        "environments": any(
            p.exists()
            for p in (
                root / "cli" / ".venv",
                backend_dir / ".venv",
                web_dir / ".venv",
                web_dir / "frontend" / "node_modules",
                web_dir / "webui" / "dist",
            )
        ),
        "path": _path_shim_exists(),
        "state": state.state_file().is_file(),
        "user-data": any(
            p.exists()
            for p in (
                backend_dir / ".env",
                web_dir / ".env",
                backend_dir / "rona.db",
                backend_dir / "rona_checkpoints.db",
            )
        ),
        "tool-packages": bool(_custom_package_paths(root)),
        "runtime": any(p.exists() for p in (backend_dir / "rona.pid", web_dir / "webui.pid")),
    }


def _stop_running_processes(root: Path, *, auto_yes: bool, interactive: bool) -> None:
    """Best-effort: a locked backend .venv (Windows) would make removing
    it fail, so we try to stop tracked processes first. Never blocks on
    input() in non-interactive mode -- without --yes there, a running
    process is just left alone and reported.
    """
    targets = (
        ("backend", root / "backend" / "rona.pid"),
        ("web", root / "web-client" / "webui.pid"),
    )
    for label, pid_path in targets:
        pid = procutil.read_pid_file(pid_path)
        if pid is None or not procutil.pid_alive(pid):
            continue
        ui.warn(i18n.t("uninstall.process_running", label=label, pid=pid))
        if not interactive and not auto_yes:
            continue
        if auto_yes or ui.confirm(i18n.t("uninstall.confirm_stop", label=label), default=True):
            procutil.kill_tree(pid)
            procutil.clear_pid_file(pid_path)
            ui.ok(i18n.t("uninstall.process_stopped", label=label))


def _select_items(available: dict[str, bool]) -> list[str]:
    options = [(item, i18n.t(_label_key(item)), False, "") for item in _ITEMS if available[item]]
    if not options:
        return []
    return ui.select_components(options)


def _remove_environments(root: Path) -> None:
    for path in (
        root / "cli" / ".venv",
        root / "cli" / "rona_cli.egg-info",
        root / "backend" / ".venv",
        root / "web-client" / ".venv",
        root / "web-client" / "frontend" / "node_modules",
        root / "web-client" / "webui" / "dist",
    ):
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)


def _remove_state(root: Path) -> None:
    path = state.state_file()
    if path.is_file():
        path.unlink(missing_ok=True)


def _remove_user_data(root: Path) -> None:
    backend_dir = root / "backend"
    web_dir = root / "web-client"
    for path in (
        backend_dir / ".env",
        backend_dir / ".env.bak",
        web_dir / ".env",
        web_dir / ".env.bak",
        backend_dir / "rona.db",
        backend_dir / "rona.db-wal",
        backend_dir / "rona.db-shm",
        backend_dir / "rona_checkpoints.db",
        backend_dir / "rona_checkpoints.db-wal",
        backend_dir / "rona_checkpoints.db-shm",
        backend_dir / "rona.log",
    ):
        path.unlink(missing_ok=True)
    for log_file in backend_dir.glob("rona.log.*"):
        log_file.unlink(missing_ok=True)


def _remove_tool_packages(root: Path) -> None:
    for path in _custom_package_paths(root):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
    (root / "backend" / "toolbox" / "custom" / "installed.json").unlink(missing_ok=True)


def _remove_runtime(root: Path) -> None:
    backend_dir = root / "backend"
    web_dir = root / "web-client"
    for path in (
        backend_dir / "rona.pid",
        web_dir / "webui.pid",
        web_dir / "webui.lock",
        web_dir / "webui.log",
    ):
        path.unlink(missing_ok=True)
    for log_file in web_dir.glob("webui.log.*"):
        log_file.unlink(missing_ok=True)


_REMOVERS = {
    "environments": _remove_environments,
    "state": _remove_state,
    "user-data": _remove_user_data,
    "tool-packages": _remove_tool_packages,
    "runtime": _remove_runtime,
    # "path" is handled separately, via pathsetup.remove() -- it isn't a
    # plain filesystem remover (it also edits the registry/rc file).
}


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    # Same chicken-and-egg reason as installer/main.py's own _parse_args:
    # this runs before a language has been asked/resolved, so its own
    # help/description text stays static Turkish.
    parser = argparse.ArgumentParser(prog="uninstall", description="Rona kaldırma aracı")
    parser.add_argument("--yes", action="store_true", help="hiç sormadan devam et")
    parser.add_argument("--json", action="store_true", help="sonucu JSON olarak ver")
    parser.add_argument(
        "--items",
        default=None,
        help="virgülle ayrılmış kaldırılacak öğe listesi: " + ", ".join(_ITEMS),
    )
    parser.add_argument("--lang", choices=i18n.SUPPORTED, default=None, help="kaldırma aracının dili")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_streams()
    args = _parse_args(argv)

    if args.lang:
        i18n.set_language(args.lang)
    elif args.yes or args.json:
        i18n.set_language(i18n.DEFAULT_LANGUAGE)
    else:
        i18n.set_language(i18n.ask_language())

    non_interactive = args.yes or args.json

    available = _detect(REPO_ROOT)
    if not any(available.values()):
        ui.info(i18n.t("uninstall.nothing_found"))
        return 0

    if non_interactive:
        _stop_running_processes(REPO_ROOT, auto_yes=args.yes, interactive=False)
        if not args.items:
            ui.error(i18n.t("uninstall.items_required"))
            return 1
        requested = {item.strip() for item in args.items.split(",") if item.strip()}
        unknown = requested - set(_ITEMS)
        if unknown:
            ui.error(i18n.t("uninstall.unknown_items", names=", ".join(sorted(unknown))))
            return 1
        selected = [item for item in _ITEMS if item in requested and available[item]]
    else:
        ui.step(i18n.t("uninstall.title"))
        _stop_running_processes(REPO_ROOT, auto_yes=args.yes, interactive=True)
        selected = _select_items(available)

    if not selected:
        ui.info(i18n.t("uninstall.none_selected"))
        return 0

    if "user-data" in selected and not non_interactive:
        ui.warn(i18n.t("uninstall.user_data_warning"))
        if not ui.confirm(i18n.t("uninstall.confirm_user_data"), default=False):
            selected.remove("user-data")
            ui.info(i18n.t("uninstall.user_data_kept"))

    removed: list[str] = []
    for item in selected:
        if item == "path":
            pathsetup.remove(auto_yes=args.yes)
        else:
            _REMOVERS[item](REPO_ROOT)
        removed.append(item)

    if args.json:
        print(jsonlib.dumps({"ok": True, "removed": removed}, ensure_ascii=False))
    else:
        ui.ok(i18n.t("uninstall.done", items=", ".join(removed)))
        ui.info(i18n.t("uninstall.repo_kept_hint"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
