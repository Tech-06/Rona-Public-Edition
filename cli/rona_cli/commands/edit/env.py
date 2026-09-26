"""`rona edit env` -- open a component's .env file in the user's editor.

There's no `--cli` variant: the CLI itself is stdlib-only and keeps no
.env of its own (see cli/README.md).

`_editor_command` is also reused by `rona_cli.commands.edit.prompt`, which
needs the editor to actually block until the user closes the file (it has
to read the file back afterwards) -- hence the `wait` flag.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys

from rona_cli import i18n, ui
from rona_cli.paths import RonaNotFoundError, RonaPaths, find_root


def _split_editor(value: str) -> list[str]:
    # A bare path to an existing file is one argument even with spaces in it
    # (C:\Program Files\...), exactly as before `$EDITOR` could carry flags.
    if os.path.isfile(value):
        return [value]
    if os.name == "nt":
        # POSIX-mode shlex treats a backslash as an escape and would mangle
        # a Windows path; non-POSIX mode keeps it but leaves quotes on tokens.
        return [part.strip('"') for part in shlex.split(value, posix=False)]
    return shlex.split(value)


def _editor_command(wait: bool = False) -> list[str]:
    """Build the argv prefix for the user's editor.

    `$VISUAL`/`$EDITOR` may be a whole command line (e.g. ``code --wait``),
    so it's split rather than treated as a single executable name (see
    `_split_editor`). ``wait=True`` matters only for the macOS `open`
    fallback: launched plainly, `open` starts the app and returns
    immediately, so a caller that must read the file back afterwards needs
    `-W` to make it wait for the app to close. Every other branch already
    blocks in the foreground on its own (Notepad, nano, or whatever
    `$VISUAL`/`$EDITOR` names).
    """
    for var in ("VISUAL", "EDITOR"):
        value = os.environ.get(var)
        if value:
            return _split_editor(value)
    if sys.platform == "win32":
        return ["notepad"]
    if sys.platform == "darwin":
        return ["open", "-W", "-t"] if wait else ["open", "-t"]
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
