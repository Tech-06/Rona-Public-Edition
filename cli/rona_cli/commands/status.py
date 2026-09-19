"""`rona status` -- a combined snapshot of the backend, the web dashboard,
and the installed optional tool packages.
"""

from __future__ import annotations

import argparse
import json as jsonlib

from rona_cli import ui
from rona_cli.commands import server, web
from rona_cli.paths import RonaNotFoundError, RonaPaths, find_root


def _installed_packages(paths: RonaPaths) -> list[str]:
    if not paths.installed_packages_lockfile.is_file():
        return []
    try:
        data = jsonlib.loads(paths.installed_packages_lockfile.read_text(encoding="utf-8"))
    except (OSError, jsonlib.JSONDecodeError):
        return []
    return sorted(data.get("packages", {}).keys())


def _run(args: argparse.Namespace) -> int:
    try:
        root = find_root(args.root)
    except RonaNotFoundError as exc:
        if args.json:
            print(jsonlib.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            ui.error(str(exc))
        return 1

    paths = RonaPaths(root)
    backend = server.describe(paths)
    dashboard = web.describe(paths)
    packages = _installed_packages(paths)

    if args.json:
        print(
            jsonlib.dumps(
                {
                    "ok": True,
                    "root": str(root),
                    "backend": backend,
                    "web": dashboard,
                    "packages": packages,
                },
                ensure_ascii=False,
            )
        )
        return 0

    ui.heading(f"Rona kurulumu: {root}")
    ui.info()

    if backend.get("running"):
        ui.ok(
            f"Backend  çalışıyor  (uptime {backend.get('uptime_seconds', '?')}s, "
            f"model {backend.get('flash_model', '?')})"
        )
    else:
        ui.warn(f"Backend  çalışmıyor  ({backend.get('detail', '')})")

    if dashboard.get("running"):
        ui.ok(f"Web      çalışıyor  (pid {dashboard.get('pid')}, uptime {dashboard.get('uptime_seconds', '?')}s)")
    else:
        ui.warn(f"Web      çalışmıyor  ({dashboard.get('detail', '')})")

    ui.info()
    if packages:
        ui.info(f"Kurulu araç paketleri ({len(packages)}): {', '.join(packages)}")
    else:
        ui.info("Kurulu araç paketi yok.")

    return 0


def register(subparsers, common) -> None:
    parser = subparsers.add_parser(
        "status", parents=[common], help="Backend, web ve araç paketlerinin durumunu göster"
    )
    parser.set_defaults(func=_run)
