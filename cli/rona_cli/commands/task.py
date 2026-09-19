"""`rona task list|del|toggle` -- a thin CLI over the backend's /api/tasks*
endpoints (see app/dashboard.py). Needs a running, reachable backend:
toggling a task's status also (un)registers it with the live in-process
scheduler (trigger/scheduler.py) -- writing straight to rona.db would not.
"""

from __future__ import annotations

import argparse
import json as jsonlib

from rona_cli import http, ui
from rona_cli.backend_client import BackendUnavailable, backend_client
from rona_cli.paths import RonaNotFoundError, RonaPaths, find_root

_STATUSES = ("all", "active", "passive")


def _resolve_client(args: argparse.Namespace) -> tuple[http.Client | None, str | None]:
    try:
        paths = RonaPaths(find_root(args.root))
        return backend_client(paths), None
    except (RonaNotFoundError, BackendUnavailable) as exc:
        return None, str(exc)


def _emit_error(args: argparse.Namespace, message: str) -> None:
    if args.json:
        print(jsonlib.dumps({"ok": False, "error": message}, ensure_ascii=False))
    else:
        ui.error(message)


def _cmd_list(args: argparse.Namespace) -> int:
    client, error = _resolve_client(args)
    if client is None:
        _emit_error(args, error)
        return 1
    path = http.build_query("/api/tasks", {"status": args.status, "limit": args.limit})
    try:
        result = client.get(path)
    except http.ApiError as exc:
        _emit_error(args, str(exc))
        return 1
    if args.json:
        print(jsonlib.dumps(result, ensure_ascii=False))
        return 0
    tasks = result.get("tasks", [])
    if not tasks:
        ui.info("Görev yok.")
        return 0
    for task in tasks:
        next_run = task.get("next_run") or "-"
        ui.info(f"[{task['status']:>7}] {task['id']}  {task['name']}  (sıradaki: {next_run})")
    return 0


def _cmd_del(args: argparse.Namespace) -> int:
    if not args.yes and not args.json:
        confirmed = ui.confirm(f"{args.id} görevi silinsin mi?", default=False)
        if not confirmed:
            ui.info("Vazgeçildi.")
            return 1

    client, error = _resolve_client(args)
    if client is None:
        _emit_error(args, error)
        return 1
    try:
        result = client.delete(f"/api/tasks/{args.id}")
    except http.ApiError as exc:
        _emit_error(args, str(exc))
        return 1
    if args.json:
        print(jsonlib.dumps(result, ensure_ascii=False))
    else:
        ui.ok("Görev silindi.")
    return 0


def _cmd_toggle(args: argparse.Namespace) -> int:
    client, error = _resolve_client(args)
    if client is None:
        _emit_error(args, error)
        return 1
    try:
        task = client.get(f"/api/tasks/{args.id}")
    except http.ApiError as exc:
        _emit_error(args, str(exc))
        return 1
    new_status = "passive" if task["status"] == "active" else "active"
    try:
        result = client.post(f"/api/tasks/{args.id}/status", {"status": new_status})
    except http.ApiError as exc:
        _emit_error(args, str(exc))
        return 1
    if args.json:
        print(jsonlib.dumps(result, ensure_ascii=False))
    else:
        ui.ok(f"Görev artık {new_status}.")
    return 0


def register(subparsers, common) -> None:
    parser = subparsers.add_parser("task", parents=[common], help="Zamanlanmış görevleri yönet")
    sub = parser.add_subparsers(dest="task_command", required=True)

    p_list = sub.add_parser("list", parents=[common], help="Görevleri listele")
    p_list.add_argument("--status", default="all", choices=_STATUSES)
    p_list.add_argument("--limit", type=int, default=100)
    p_list.set_defaults(func=_cmd_list)

    p_del = sub.add_parser("del", parents=[common], help="Görevi sil")
    p_del.add_argument("id")
    p_del.add_argument("--yes", action="store_true", help="onay sorma")
    p_del.set_defaults(func=_cmd_del)

    p_toggle = sub.add_parser("toggle", parents=[common], help="Aktif/pasif durumunu değiştir")
    p_toggle.add_argument("id")
    p_toggle.set_defaults(func=_cmd_toggle)
