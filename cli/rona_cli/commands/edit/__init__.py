"""`rona edit ...` -- the edit command group: model, auth, env, memory."""

from __future__ import annotations

from rona_cli.commands.edit import auth, env, memory, model


def register(subparsers, common) -> None:
    parser = subparsers.add_parser("edit", parents=[common], help="Yapılandırmayı düzenle")
    sub = parser.add_subparsers(dest="edit_command", required=True)
    for module in (model, auth, env, memory):
        module.register(sub, common)
