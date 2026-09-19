"""`rona edit memory search|add|edit|delete|stats` -- a thin CLI over the
backend's /api/data/memories* endpoints (see app/dashboard.py). Unlike
`rona edit model`/`auth`, this needs a running, reachable backend.
"""

from __future__ import annotations

import argparse
import json as jsonlib

from rona_cli import http, ui
from rona_cli.backend_client import BackendUnavailable, backend_client
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
        ui.info("Sonuç yok.")
        return 0
    for item in results:
        ui.info(f"[{item['id']}] ({item['layer']}, skor {item['score']}) {item['content']}")
    return 0


def _cmd_add(args: argparse.Namespace) -> int:
    metadata = None
    if args.metadata:
        try:
            metadata = jsonlib.loads(args.metadata)
        except jsonlib.JSONDecodeError as exc:
            _emit_error(args, f"metadata geçerli bir JSON nesnesi değil: {exc}")
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
        ui.ok(f"Hafıza eklendi (id {result.get('id')}).")
    return 0


def _cmd_edit(args: argparse.Namespace) -> int:
    metadata = None
    if args.metadata is not None:
        try:
            metadata = jsonlib.loads(args.metadata)
        except jsonlib.JSONDecodeError as exc:
            _emit_error(args, f"metadata geçerli bir JSON nesnesi değil: {exc}")
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
        _emit_error(args, "değiştirilecek en az bir alan belirt (--layer/--content/--person/--metadata)")
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
        ui.ok("Hafıza güncellendi.")
    return 0


def _cmd_delete(args: argparse.Namespace) -> int:
    if not args.yes and not args.json:
        confirmed = ui.confirm(f"{args.id} numaralı hafıza silinsin mi?", default=False)
        if not confirmed:
            ui.info("Vazgeçildi.")
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
        ui.ok("Hafıza silindi.")
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
    ui.info(f"Toplam: {result['total']}")
    for layer, count in result["by_layer"].items():
        ui.info(f"  {layer}: {count}")
    ui.info(
        f"Genel (kişisiz): {result['general_count']}, "
        f"kişiye bağlı: {result['person_linked_count']}"
    )
    if result["oldest_created_at"]:
        ui.info(f"En eski: {result['oldest_created_at']}, en yeni: {result['newest_created_at']}")
    ui.info(f"Toplam erişim sayısı: {result['total_access_count']}")
    return 0


def register(subparsers, common) -> None:
    parser = subparsers.add_parser("memory", parents=[common], help="Hafıza kayıtlarını yönet")
    sub = parser.add_subparsers(dest="memory_command", required=True)

    p_search = sub.add_parser("search", parents=[common], help="Anlamsal arama yap")
    p_search.add_argument("query")
    p_search.add_argument("--person", default=None)
    p_search.add_argument("--date-from", dest="date_from", default=None)
    p_search.add_argument("--date-to", dest="date_to", default=None)
    p_search.add_argument("--limit", type=int, default=10)
    p_search.set_defaults(func=_cmd_search)

    p_add = sub.add_parser("add", parents=[common], help="Yeni hafıza ekle")
    p_add.add_argument("content")
    p_add.add_argument("--layer", required=True, choices=_LAYERS)
    p_add.add_argument("--person", type=int, default=None, help="kişi ID'si")
    p_add.add_argument("--metadata", default=None, help="JSON nesnesi")
    p_add.set_defaults(func=_cmd_add)

    p_edit = sub.add_parser("edit", parents=[common], help="Var olan hafızayı düzenle")
    p_edit.add_argument("id", type=int)
    p_edit.add_argument("--layer", default=None, choices=_LAYERS)
    p_edit.add_argument("--content", default=None)
    p_edit.add_argument("--person", type=int, default=None, help="kişi ID'si")
    p_edit.add_argument("--metadata", default=None, help="JSON nesnesi")
    p_edit.set_defaults(func=_cmd_edit)

    p_delete = sub.add_parser("delete", parents=[common], help="Hafızayı sil")
    p_delete.add_argument("id", type=int)
    p_delete.add_argument("--yes", action="store_true", help="onay sorma")
    p_delete.set_defaults(func=_cmd_delete)

    p_stats = sub.add_parser("stats", parents=[common], help="Hafıza istatistiklerini göster")
    p_stats.set_defaults(func=_cmd_stats)
