"""`rona log list|show|del|tail` -- execution history (task_runs +
subagent_runs, via the backend's /api/runs* endpoints) and a live tail of
the text log file (`GET /api/logs`, falling back to reading
backend/rona.log directly when the backend isn't reachable).
"""

from __future__ import annotations

import argparse
import json as jsonlib
import time
from pathlib import Path

from rona_cli import http, ui
from rona_cli.backend_client import BackendUnavailable, backend_client, require_running
from rona_cli.paths import RonaNotFoundError, RonaPaths, find_root

_KINDS = ("all", "task", "subagent")


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
    reported = False if args.unread else None
    path = http.build_query(
        "/api/runs",
        {"kind": args.kind, "status": args.status, "reported": reported, "limit": args.limit},
    )
    try:
        result = client.get(path)
    except http.ApiError as exc:
        _emit_error(args, str(exc))
        return 1
    if args.json:
        print(jsonlib.dumps(result, ensure_ascii=False))
        return 0
    runs = result.get("runs", [])
    if not runs:
        ui.info("Kayıt yok.")
        return 0
    for run in runs:
        marker = " " if run["reported"] else "*"
        ts = run.get("started_at") or run.get("created_at") or "?"
        label = run.get("task_name") or run.get("task") or ""
        ui.info(f"{marker} [{run['kind']:>8}] {run['id']}  {run['status']:>9}  {ts}  {label}")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    client, error = _resolve_client(args)
    if client is None:
        _emit_error(args, error)
        return 1
    try:
        result = client.get(f"/api/runs/{args.id}")
    except http.ApiError as exc:
        _emit_error(args, str(exc))
        return 1
    if args.json:
        print(jsonlib.dumps(result, ensure_ascii=False))
        return 0
    for key, value in result.items():
        ui.info(f"{key}: {value}")
    return 0


def _cmd_del(args: argparse.Namespace) -> int:
    if not args.yes and not args.json:
        confirmed = ui.confirm(f"{args.id} kaydı silinsin mi?", default=False)
        if not confirmed:
            ui.info("Vazgeçildi.")
            return 1

    client, error = _resolve_client(args)
    if client is None:
        _emit_error(args, error)
        return 1
    try:
        result = client.delete(f"/api/runs/{args.id}")
    except http.ApiError as exc:
        if exc.status == 409:
            _emit_error(args, "kayıt henüz kullanıcıya bildirilmedi; önce okunmuş olması gerekir")
        else:
            _emit_error(args, str(exc))
        return 1
    if args.json:
        print(jsonlib.dumps(result, ensure_ascii=False))
    else:
        ui.ok("Kayıt silindi.")
    return 0


def _line_matches(line: str, level: str | None, grep: str | None) -> bool:
    if level and f" {level} " not in line:
        return False
    return not (grep and grep.lower() not in line.lower())


def _tail_remote(client: http.Client, level: str | None, grep: str | None) -> int:
    path = http.build_query("/api/logs", {"level": level, "q": grep})
    try:
        for raw_line in client.stream_lines(path, timeout=30.0):
            if not raw_line.startswith("data: "):
                continue  # skip blank lines and ": ping" heartbeats
            try:
                line = jsonlib.loads(raw_line[len("data: ") :])
            except jsonlib.JSONDecodeError:
                continue
            print(line, flush=True)
    except http.ApiError as exc:
        ui.error(f"Log akışı kesildi: {exc}")
        return 1
    except KeyboardInterrupt:
        pass
    return 0


def _tail_local(log_path: Path, level: str | None, grep: str | None) -> int:
    if not log_path.exists():
        ui.error(f"Log dosyası bulunamadı: {log_path}")
        return 1
    ui.warn("Backend çalışmıyor; yerel log dosyası izleniyor.")
    offset = log_path.stat().st_size
    try:
        while True:
            time.sleep(1.0)
            size = log_path.stat().st_size
            if size < offset:  # rotated
                offset = 0
            if size == offset:
                continue
            with log_path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                chunk = handle.read(size - offset)
            offset = size
            for line in chunk.splitlines():
                if line and _line_matches(line, level, grep):
                    print(line, flush=True)
    except KeyboardInterrupt:
        pass
    return 0


def _cmd_tail(args: argparse.Namespace) -> int:
    try:
        paths = RonaPaths(find_root(args.root))
    except RonaNotFoundError as exc:
        ui.error(str(exc))
        return 1
    try:
        client = backend_client(paths)
        require_running(client)
    except BackendUnavailable:
        return _tail_local(paths.backend_log, args.level, args.grep)
    return _tail_remote(client, args.level, args.grep)


def register(subparsers, common) -> None:
    parser = subparsers.add_parser("log", parents=[common], help="Çalışma geçmişi ve canlı log")
    sub = parser.add_subparsers(dest="log_command", required=True)

    p_list = sub.add_parser("list", parents=[common], help="Geçmiş kayıtları listele")
    p_list.add_argument("--kind", default="all", choices=_KINDS)
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--unread", action="store_true", help="sadece henüz bildirilmemiş kayıtlar")
    p_list.add_argument("--limit", type=int, default=50)
    p_list.set_defaults(func=_cmd_list)

    p_show = sub.add_parser("show", parents=[common], help="Bir kaydın detayını göster")
    p_show.add_argument("id")
    p_show.set_defaults(func=_cmd_show)

    p_del = sub.add_parser("del", parents=[common], help="Bildirilmiş bir kaydı sil")
    p_del.add_argument("id")
    p_del.add_argument("--yes", action="store_true", help="onay sorma")
    p_del.set_defaults(func=_cmd_del)

    p_tail = sub.add_parser("tail", parents=[common], help="Canlı log akışını izle")
    p_tail.add_argument("--level", default=None, help="ör. INFO, ERROR")
    p_tail.add_argument("--grep", default=None, help="metin filtresi")
    p_tail.set_defaults(func=_cmd_tail)
