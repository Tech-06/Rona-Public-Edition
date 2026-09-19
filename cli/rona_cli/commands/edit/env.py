"""`rona edit env` -- open a component's .env file in the user's editor.

There's no `--cli` variant: the CLI itself is stdlib-only and keeps no
.env of its own (see cli/README.md).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from rona_cli import i18n, ui
from rona_cli.paths import RonaNotFoundError, RonaPaths, find_root


def _editor_command() -> list[str]:
    for var in ("VISUAL", "EDITOR"):
        value = os.environ.get(var)
        if value:
            return [value]
    if sys.platform == "win32":
        return ["notepad"]
    if sys.platform == "darwin":
        return ["open", "-t"]
    return ["nano"]


def _cmd(args: argparse.Namespace) -> int:
    try:
        paths = RonaPaths(find_root(args.root))
    except RonaNotFoundError as exc:
        ui.error(str(exc))
        return 1

    target_path = paths.web_env if args.web else paths.backend_env
    if not target_path.exists():
        ui.warn(i18n.t("env.creating", path=target_path))
        target_path.touch()

    command = [*_editor_command(), str(target_path)]
    try:
        result = subprocess.run(command, check=False)
    except FileNotFoundError:
        ui.error(i18n.t("env.editor_failed", command=" ".join(command)))
        ui.info(i18n.t("env.open_manually", path=target_path))
        return 1
    return result.returncode


def register(subparsers, common) -> None:
    parser = subparsers.add_parser("env", parents=[common], help=i18n.t("env.help_group"))
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--backend", action="store_true", help=i18n.t("env.help_backend_flag"))
    group.add_argument("--web", action="store_true", help=i18n.t("env.help_web_flag"))
    parser.set_defaults(func=_cmd)
