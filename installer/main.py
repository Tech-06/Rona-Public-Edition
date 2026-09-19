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

from installer import detect, envgen, prereq, state, ui
from installer.steps import backend as backend_step
from installer.steps import cli as cli_step
from installer.steps import web as web_step

MIN_PYTHON = (3, 11)
MIN_NODE_MAJOR = 18
_COMPONENTS = ("cli", "backend", "web")

_LABELS = {
    "cli": "CLI      rona yönetim aracı",
    "backend": "Backend  Rona çekirdeği (:8000)",
    "web": "Web      Web paneli (:8016)",
}


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
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
    return parser.parse_args(argv)


def _select_components(args: argparse.Namespace, installed: detect.InstalledComponents) -> list[str] | None:
    installed_dict = installed.as_dict()

    if args.repair:
        selected = [name for name in _COMPONENTS if installed_dict[name]]
        if not selected:
            ui.error("Onarılacak kurulu bir bileşen bulunamadı.")
            return None
        return selected

    if args.components:
        requested = {c.strip() for c in args.components.split(",") if c.strip()}
        unknown = requested - set(_COMPONENTS)
        if unknown:
            ui.error(f"Bilinmeyen bileşen(ler): {', '.join(sorted(unknown))}")
            return None
        return [c for c in _COMPONENTS if c in requested]

    if args.yes or args.json:
        return list(_COMPONENTS)

    options = [
        (name, _LABELS[name], True, "kurulu — yeniden kurulacak" if installed_dict[name] else "")
        for name in _COMPONENTS
    ]
    return ui.select_components(options)


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_streams()
    args = _parse_args(argv)

    ui.step("Ön kontroller")
    py_version = detect.python_version()
    if py_version < MIN_PYTHON:
        ui.error(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ gerekli, bulunan: "
            f"{py_version[0]}.{py_version[1]}."
        )
        return 1
    ui.ok(f"Python {py_version[0]}.{py_version[1]}.{py_version[2]}")

    if not detect.git_available():
        ui.warn("git bulunamadı (bu kurulum için gerekli değil, sadece bilgi amaçlı).")

    os_name = detect.detect_os()
    pkg_manager = detect.package_manager(os_name)
    installed = detect.InstalledComponents(REPO_ROOT)

    selected = _select_components(args, installed)
    if not selected:
        if selected is not None:
            ui.warn("Hiçbir bileşen seçilmedi, çıkılıyor.")
        return 1

    if "web" in selected:
        node = detect.node_version()
        if node is None or node[0] < MIN_NODE_MAJOR:
            if not prereq.ensure_prerequisite("Node.js", "node", False, os_name, pkg_manager, args.yes):
                ui.error("Node.js olmadan web paneli kurulamaz (--components ile çıkarabilirsin).")
                return 1
        else:
            ui.ok(f"Node.js {node[0]}.{node[1]}.{node[2]}")

    installed_dict = installed.as_dict()
    results: dict[str, bool] = {}
    if "cli" in selected:
        results["cli"] = cli_step.install(REPO_ROOT, reinstall=installed_dict["cli"])
    if "backend" in selected:
        results["backend"] = backend_step.install(REPO_ROOT, reinstall=installed_dict["backend"])
    if "web" in selected:
        results["web"] = web_step.install(REPO_ROOT, reinstall=installed_dict["web"])

    backend_env_path = REPO_ROOT / "backend" / ".env"
    if backend_env_path.exists():
        envgen.ensure_auth_token(REPO_ROOT, install_web="web" in selected)
        ui.ok("AUTH_TOKEN ayarlandı (backend ve web .env dosyaları eşleşiyor).")

    all_ok = bool(results) and all(results.values())
    if all_ok:
        state.write_state(REPO_ROOT, {name: (name in selected) for name in _COMPONENTS})

    ui.step("Özet")
    for name, succeeded in results.items():
        (ui.ok if succeeded else ui.error)(f"{name}: {'tamam' if succeeded else 'başarısız'}")

    if all_ok:
        ui.info("")
        ui.info("Sıradaki adımlar:")
        if "backend" in selected:
            ui.info("  rona edit model flash   # zorunlu: Flash model bilgilerini gir")
            ui.info("  rona server start")
        if "web" in selected:
            ui.info("  rona web start")

    if args.json:
        print(jsonlib.dumps({"ok": all_ok, "results": results}, ensure_ascii=False))

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
