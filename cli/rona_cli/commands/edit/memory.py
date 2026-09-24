"""`rona edit memory search|add|edit|delete|list|archive|archived|restore|
purge|stats` -- a thin CLI over the backend's /api/data/memories* and
/api/data/archive* endpoints (see app/dashboard.py). Unlike `rona edit
model`/`auth`, this needs a running, reachable backend.

The `consolidate` subgroup (run/status/config) lives in its own module,
`memory_consolidate.py`, and is wired in at the bottom of `register()`.
"""

from __future__ import annotations

import argparse
import json as jsonlib

from rona_cli import http, i18n, ui
from rona_cli.backend_client import BackendUnavailable, backend_client
from rona_cli.commands.edit import memory_consolidate
from rona_cli.paths import RonaNotFoundError, RonaPaths, find_root

_LAYERS = ("deep", "seasonal", "short")


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


def _cmd_search(args: argparse.Namespace) -> int:
    client, error = _resolve_client(args)
    if client is None:
        _emit_error(args, error)
        return 1
    path = http.build_query(
        "/api/data/memories/search",
        {
            "q": args.query,
            "person": args.person,
            "date_from": args.date_from,
            "date_to": args.date_to,
            "limit": args.limit,
        },
    )
    try:
        result = client.get(path)
    except http.ApiError as exc:
        _emit_error(args, str(exc))
        return 1
    if args.json:
        print(jsonlib.dumps(result, ensure_ascii=False))
        return 0
    results = result.get("results", [])
    if not results:
        ui.info(i18n.t("memory.no_results"))
        return 0
    for item in results:
        ui.info(
            i18n.t(
                "memory.result_line",
                id=item["id"],
                layer=item["layer"],
                score=item["score"],
                content=item["content"],
            )
        )
    return 0


def _cmd_add(args: argparse.Namespace) -> int:
    metadata = None
    if args.metadata:
        try:
            metadata = jsonlib.loads(args.metadata)
        except jsonlib.JSONDecodeError as exc:
            _emit_error(args, i18n.t("common.metadata_invalid_json", exc=exc))
            return 1

    client, error = _resolve_client(args)
    if client is None:
        _emit_error(args, error)
        return 1
    payload = {
        "layer": args.layer,
        "content": args.content,
        "person_id": args.person,
        "metadata": metadata,
    }
    try:
        result = client.post("/api/data/memories", payload)
    except http.ApiError as exc:
        _emit_error(args, str(exc))
        return 1
    if args.json:
        print(jsonlib.dumps(result, ensure_ascii=False))
    else:
        ui.ok(i18n.t("memory.added", id=result.get("id")))
    return 0


def _cmd_edit(args: argparse.Namespace) -> int:
    metadata = None
    if args.metadata is not None:
        try:
            metadata = jsonlib.loads(args.metadata)
        except jsonlib.JSONDecodeError as exc:
            _emit_error(args, i18n.t("common.metadata_invalid_json", exc=exc))
            return 1

    payload: dict = {}
    if args.layer is not None:
        payload["layer"] = args.layer
    if args.content is not None:
        payload["content"] = args.content
    if args.person is not None:
        payload["person_id"] = args.person
    if metadata is not None:
        payload["metadata"] = metadata
    if not payload:
        _emit_error(args, i18n.t("memory.edit_no_fields"))
        return 1

    client, error = _resolve_client(args)
    if client is None:
        _emit_error(args, error)
        return 1
    try:
        result = client.put(f"/api/data/memories/{args.id}", payload)
    except http.ApiError as exc:
        _emit_error(args, str(exc))
        return 1
    if args.json:
        print(jsonlib.dumps(result, ensure_ascii=False))
    else:
        ui.ok(i18n.t("memory.updated"))
    return 0


def _cmd_delete(args: argparse.Namespace) -> int:
    if not args.yes and not args.json:
        confirmed = ui.confirm(i18n.t("memory.confirm_delete", id=args.id), default=False)
        if not confirmed:
            ui.info(i18n.t("common.cancelled"))
            return 1

    client, error = _resolve_client(args)
    if client is None:
        _emit_error(args, error)
        return 1
    try:
        result = client.delete(f"/api/data/memories/{args.id}")
    except http.ApiError as exc:
        _emit_error(args, str(exc))
        return 1
    if args.json:
        print(jsonlib.dumps(result, ensure_ascii=False))
    else:
        ui.ok(i18n.t("memory.deleted"))
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    client, error = _resolve_client(args)
    if client is None:
        _emit_error(args, error)
        return 1
    try:
        result = client.get("/api/data/memories/stats")
    except http.ApiError as exc:
        _emit_error(args, str(exc))
        return 1
    if args.json:
        print(jsonlib.dumps(result, ensure_ascii=False))
        return 0
    ui.info(i18n.t("memory.stats_total", total=result["total"]))
    for layer, count in result["by_layer"].items():
        ui.info(f"  {layer}: {count}")
    ui.info(
        i18n.t(
            "memory.stats_split",
            general=result["general_count"],
            linked=result["person_linked_count"],
        )
    )
    if result["oldest_created_at"]:
        ui.info(
            i18n.t(
                "memory.stats_range",
                oldest=result["oldest_created_at"],
                newest=result["newest_created_at"],
            )
        )
    ui.info(i18n.t("memory.stats_access_count", count=result["total_access_count"]))
    if "archived_count" in result:
        ui.info(i18n.t("memory.stats_archived", count=result["archived_count"]))
    if "last_consolidation" in result:
        last = result["last_consolidation"]
        if last:
            ui.info(
                i18n.t(
                    "memory.stats_last_consolidation",
                    finished_at=last["finished_at"],
                    triggered_by=last["triggered_by"],
                    promoted_short=last["promoted_short"],
                    promoted_seasonal=last["promoted_seasonal"],
                    archived=last["archived"],
                    deleted=last["deleted"],
                )
            )
        else:
            ui.info(i18n.t("memory.stats_no_consolidation"))
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    client, error = _resolve_client(args)
    if client is None:
        _emit_error(args, error)
        return 1
    path = http.build_query(
        "/api/data/memories",
        {
            "layer": args.layer,
            "person": args.person,
            "limit": args.limit,
            "offset": args.offset,
        },
    )
    try:
        result = client.get(path)
    except http.ApiError as exc:
        _emit_error(args, str(exc))
        return 1
    if args.json:
        print(jsonlib.dumps(result, ensure_ascii=False))
        return 0
    memories = result.get("memories", [])
    if not memories:
        ui.info(i18n.t("memory.no_memories"))
        return 0
    for item in memories:
        ui.info(
            i18n.t(
                "memory.list_line",
                id=item["id"],
                layer=item["layer"],
                hits=item.get("layer_hits", 0),
                total=item.get("access_count", 0),
                last=item.get("last_accessed") or i18n.t("memory.never"),
                content=item["content"],
            )
        )
    ui.info(
        i18n.t(
            "memory.list_footer", shown=len(memories), total=result.get("total", len(memories))
        )
    )
    return 0


def _cmd_archive(args: argparse.Namespace) -> int:
    client, error = _resolve_client(args)
    if client is None:
        _emit_error(args, error)
        return 1
    try:
        result = client.post(f"/api/data/memories/{args.id}/archive")
    except http.ApiError as exc:
        _emit_error(args, str(exc))
        return 1
    if args.json:
        print(jsonlib.dumps(result, ensure_ascii=False))
    else:
        ui.ok(i18n.t("memory.archive_ok", id=args.id, archive_id=result.get("archive_id")))
    return 0


def _cmd_archived(args: argparse.Namespace) -> int:
    client, error = _resolve_client(args)
    if client is None:
        _emit_error(args, error)
        return 1
    path = http.build_query("/api/data/archive", {"limit": args.limit, "offset": args.offset})
    try:
        result = client.get(path)
    except http.ApiError as exc:
        _emit_error(args, str(exc))
        return 1
    if args.json:
        print(jsonlib.dumps(result, ensure_ascii=False))
        return 0
    archive = result.get("archive", [])
    if not archive:
        ui.info(i18n.t("memory.archive_empty"))
        return 0
    for item in archive:
        reason = i18n.t(f"memory.archive_reason_{item['reason']}")
        ui.info(
            i18n.t(
                "memory.archived_line",
                id=item["id"],
                layer=item["layer"],
                reason=reason,
                archived_at=item["archived_at"],
                content=item["content"],
            )
        )
    return 0


def _cmd_restore(args: argparse.Namespace) -> int:
    client, error = _resolve_client(args)
    if client is None:
        _emit_error(args, error)
        return 1
    try:
        result = client.post(f"/api/data/archive/{args.archive_id}/restore")
    except http.ApiError as exc:
        _emit_error(args, str(exc))
        return 1
    if args.json:
        print(jsonlib.dumps(result, ensure_ascii=False))
    else:
        ui.ok(
            i18n.t(
                "memory.restore_ok", archive_id=args.archive_id, memory_id=result.get("memory_id")
            )
        )
    return 0


def _cmd_purge(args: argparse.Namespace) -> int:
    if not args.yes and not args.json:
        confirmed = ui.confirm(i18n.t("memory.confirm_purge", id=args.archive_id), default=False)
        if not confirmed:
            ui.info(i18n.t("common.cancelled"))
            return 1

    client, error = _resolve_client(args)
    if client is None:
        _emit_error(args, error)
        return 1
    try:
        result = client.delete(f"/api/data/archive/{args.archive_id}")
    except http.ApiError as exc:
        _emit_error(args, str(exc))
        return 1
    if args.json:
        print(jsonlib.dumps(result, ensure_ascii=False))
    else:
        ui.ok(i18n.t("memory.purge_ok"))
    return 0


def register(subparsers, common) -> None:
    parser = subparsers.add_parser("memory", parents=[common], help=i18n.t("memory.help_group"))
    sub = parser.add_subparsers(dest="memory_command", required=True)

    p_search = sub.add_parser("search", parents=[common], help=i18n.t("memory.help_search"))
    p_search.add_argument("query")
    p_search.add_argument("--person", default=None)
    p_search.add_argument("--date-from", dest="date_from", default=None)
    p_search.add_argument("--date-to", dest="date_to", default=None)
    p_search.add_argument("--limit", type=int, default=10)
    p_search.set_defaults(func=_cmd_search)

    p_add = sub.add_parser("add", parents=[common], help=i18n.t("memory.help_add"))
    p_add.add_argument("content")
    p_add.add_argument("--layer", required=True, choices=_LAYERS)
    p_add.add_argument("--person", type=int, default=None, help=i18n.t("common.help_person_id"))
    p_add.add_argument("--metadata", default=None, help=i18n.t("common.help_json_object"))
    p_add.set_defaults(func=_cmd_add)

    p_edit = sub.add_parser("edit", parents=[common], help=i18n.t("memory.help_edit"))
    p_edit.add_argument("id", type=int)
    p_edit.add_argument("--layer", default=None, choices=_LAYERS)
    p_edit.add_argument("--content", default=None)
    p_edit.add_argument("--person", type=int, default=None, help=i18n.t("common.help_person_id"))
    p_edit.add_argument("--metadata", default=None, help=i18n.t("common.help_json_object"))
    p_edit.set_defaults(func=_cmd_edit)

    p_delete = sub.add_parser("delete", parents=[common], help=i18n.t("memory.help_delete"))
    p_delete.add_argument("id", type=int)
    p_delete.add_argument("--yes", action="store_true", help=i18n.t("common.help_skip_confirm"))
    p_delete.set_defaults(func=_cmd_delete)

    p_stats = sub.add_parser("stats", parents=[common], help=i18n.t("memory.help_stats"))
    p_stats.set_defaults(func=_cmd_stats)

    p_list = sub.add_parser("list", parents=[common], help=i18n.t("memory.help_list"))
    p_list.add_argument(
        "--layer", default=None, choices=_LAYERS, help=i18n.t("memory.help_list_layer_flag")
    )
    p_list.add_argument("--person", default="all", help=i18n.t("memory.help_list_person_flag"))
    p_list.add_argument("--limit", type=int, default=50, help=i18n.t("memory.help_limit_flag"))
    p_list.add_argument("--offset", type=int, default=0, help=i18n.t("memory.help_offset_flag"))
    p_list.set_defaults(func=_cmd_list)

    p_archive = sub.add_parser("archive", parents=[common], help=i18n.t("memory.help_archive"))
    p_archive.add_argument("id", type=int)
    p_archive.set_defaults(func=_cmd_archive)

    p_archived = sub.add_parser("archived", parents=[common], help=i18n.t("memory.help_archived"))
    p_archived.add_argument("--limit", type=int, default=50, help=i18n.t("memory.help_limit_flag"))
    p_archived.add_argument("--offset", type=int, default=0, help=i18n.t("memory.help_offset_flag"))
    p_archived.set_defaults(func=_cmd_archived)

    p_restore = sub.add_parser("restore", parents=[common], help=i18n.t("memory.help_restore"))
    p_restore.add_argument("archive_id", type=int)
    p_restore.set_defaults(func=_cmd_restore)

    p_purge = sub.add_parser("purge", parents=[common], help=i18n.t("memory.help_purge"))
    p_purge.add_argument("archive_id", type=int)
    p_purge.add_argument("--yes", action="store_true", help=i18n.t("common.help_skip_confirm"))
    p_purge.set_defaults(func=_cmd_purge)

    memory_consolidate.register(sub, common)
