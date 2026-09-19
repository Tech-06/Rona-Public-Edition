"""Entry point and argument parsing for the `rona` command."""

from __future__ import annotations

import argparse
import io
import sys

from rona_cli import __version__, i18n
from rona_cli.commands import edit, log, server, status, task, tools, web


def _ensure_utf8_streams() -> None:
    """Force UTF-8 stdout/stderr so Turkish text doesn't crash on a plain
    Windows console (whose default codepage, e.g. cp1252, can't encode it).
    """
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            try:
                stream.reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


def _common_parser(*, suppress: bool) -> argparse.ArgumentParser:
    """Flags shared by the root parser and every subcommand.

    Adding this as ``parents=[...]`` on both the root parser and each
    subcommand parser lets ``--root``/``--json`` be given either before or
    after the subcommand name (e.g. both ``rona --json status`` and
    ``rona status --json`` work).

    argparse's subparsers action parses each subcommand into a *brand new*
    namespace and then copies every one of its attributes onto the outer
    namespace -- including attributes the subcommand never saw, which get
    set back to that subparser's own default. Left alone, `rona --root X
    status` would have "status"'s own (unset) `--root` default of ``None``
    silently overwrite the ``X`` the root parser already parsed. Building
    the subcommand copies with ``argument_default=SUPPRESS`` means an
    unspecified flag is simply absent from that copy instead of clobbering
    whatever the outer namespace already holds.
    """
    kwargs: dict = {"argument_default": argparse.SUPPRESS} if suppress else {}
    parser = argparse.ArgumentParser(add_help=False, **kwargs)
    parser.add_argument("--root", help=i18n.t("cli.help_root"))
    parser.add_argument("--json", action="store_true", help=i18n.t("cli.help_json"))
    return parser


def build_parser() -> argparse.ArgumentParser:
    root_common = _common_parser(suppress=False)
    sub_common = _common_parser(suppress=True)

    parser = argparse.ArgumentParser(
        prog="rona",
        description=i18n.t("cli.description"),
        parents=[root_common],
    )
    parser.add_argument("--version", action="version", version=f"rona {__version__}")

    sub = parser.add_subparsers(dest="command")

    for module in (status, server, web, edit, task, log, tools):
        module.register(sub, sub_common)

    return parser


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_streams()
    i18n.set_language(i18n.resolve_language())
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 1
    return func(args)


if __name__ == "__main__":
    sys.exit(main())
