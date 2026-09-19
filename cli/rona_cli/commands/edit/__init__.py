"""`rona edit ...` -- the edit command group: model, auth, env, memory."""

from __future__ import annotations

from rona_cli import i18n
from rona_cli.commands.edit import auth, env, lang, memory, model


def register(subparsers, common) -> None:
    parser = subparsers.add_parser("edit", parents=[common], help=i18n.t("edit.help_group"))
    sub = parser.add_subparsers(dest="edit_command", required=True)
    for module in (model, auth, env, memory, lang):
        module.register(sub, common)
