"""Durable registry of conversation ("thread") activity.

Persisted in the backend's own `rona.db` (via toolbox.db) rather than in
`rona_checkpoints.db`, which belongs to LangGraph's AsyncSqliteSaver and is
written through a single long-lived async connection guarded by its own
lock. `rona.db` already has WAL + busy_timeout wired up in toolbox.db and
is where subagents/store.py and trigger/store.py do the same kind of sync
sqlite bookkeeping from async route handlers and graph nodes.

This table replaces the old in-memory-only `_activity` dict that used to
live in graph.threads: that dict was empty after every restart, so
pre-existing conversations could never be purged again and became
permanent orphans in rona_checkpoints.db. A durable table also lets
pinning survive restarts and lets the web client learn which conversations
were deleted server-side.

Rows are never hard-deleted by the TTL purge path: `purged_at` is a
tombstone. This matters for the web client's sync logic. A conversation
id that is simply *absent* from the registry (fresh rona.db, a restart
before reconcile() has run, rona_checkpoints.db reset, ...) is NOT
evidence that it was deleted -- treating absence as deletion would wipe a
user's local chat transcripts on nothing more than a timing coincidence.
Only ids that show up in the `purged` list (via list_purged) were
definitely deleted here, and only those should ever be removed from the
client's local storage.
"""

import sqlite3
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

from toolbox import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversation_registry (
    thread_id   TEXT PRIMARY KEY,
    last_active TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    pinned      INTEGER NOT NULL DEFAULT 0,
    purged_at   TEXT
)
"""

INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_conversation_registry_scan "
    "ON conversation_registry(pinned, purged_at, last_active)"
)


def _apply_schema(connection: sqlite3.Connection) -> None:
    cursor = connection.cursor()
    cursor.execute(SCHEMA)
    cursor.execute(INDEX)
    connection.commit()


def _get_connection() -> sqlite3.Connection | None:
    """Open a connection to rona.db, self-healing the schema first.

    Every registry function goes through here rather than calling
    ensure_schema() once at import time, because the app's lifespan is not
    the only caller of touch()/etc: tests (and anything else that builds a
    graph and calls _run_turn directly) can reach these functions without
    ever running FastAPI's startup. Re-running the idempotent CREATE
    TABLE/INDEX IF NOT EXISTS statements on every call is cheap and makes
    the whole module correct regardless of call order or which rona.db
    file is currently pointed to (a real concern in tests, which swap
    toolbox.db.DB_PATH between runs).
    """
    connection = db.connect_if_exists()
    if connection is None:
        return None
    try:
        _apply_schema(connection)
    except sqlite3.Error:
        pass
    return connection


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "thread_id": row["thread_id"],
        "last_active": row["last_active"],
        "pinned": bool(row["pinned"]),
        "purged_at": row["purged_at"],
    }


def ensure_schema() -> None:
    """Create the table/index if missing.

    Every other function in this module already self-heals the schema on
    each call (see _get_connection), so this is mostly documentation of
    intent plus an explicit, early call site: it's run once at app
    startup so the very first real request doesn't pay for it, and it
    mirrors create_db.py's MIGRATIONS entry for anyone who upgrades
    without re-running that manual script.
    """
    connection = _get_connection()
    if connection is None:
        return
    connection.close()


def touch(thread_id: str) -> None:
    """Record activity on a conversation, upserting it into the registry.

    Also clears any tombstone: if a thread_id keeps being used after
    being marked purged (id reuse, or a purge racing a resumed turn), it
    is live again and should stop being reported in the `purged` list.
    """
    connection = _get_connection()
    if connection is None:
        return
    try:
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO conversation_registry (thread_id, last_active, pinned) "
            "VALUES (?, ?, 0) "
            "ON CONFLICT(thread_id) DO UPDATE SET "
            "last_active = excluded.last_active, purged_at = NULL",
            (thread_id, _now_utc()),
        )
        connection.commit()
    finally:
        connection.close()


def get(thread_id: str) -> dict[str, Any] | None:
    connection = _get_connection()
    if connection is None:
        return None
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT * FROM conversation_registry WHERE thread_id = ?", (thread_id,)
        )
        row = cursor.fetchone()
        return _row_to_dict(row) if row is not None else None
    finally:
        connection.close()


def set_pinned(thread_id: str, pinned: bool) -> dict[str, Any]:
    """Upsert the pin state. Never raises for an unknown thread_id -- a
    conversation pinned before the registry has seen it (e.g. pinned
    right after creation, before any purge-relevant activity) is simply
    created on the spot. Returning a 404 here would force the client to
    track a "pinned locally but not yet on the server" split-brain state.

    Pinning does NOT refresh `last_active`: a conversation pinned for a
    long time must not have its idle clock silently reset just because
    someone looked at it. Unpinning DOES refresh `last_active`, granting
    a fresh full TTL window instead of deleting a long-pinned conversation
    on the very next purge tick the moment it's unpinned.
    """
    connection = _get_connection()
    if connection is None:
        raise RuntimeError("rona.db is not available")
    try:
        cursor = connection.cursor()
        if pinned:
            cursor.execute(
                "INSERT INTO conversation_registry (thread_id, last_active, pinned) "
                "VALUES (?, ?, 1) "
                "ON CONFLICT(thread_id) DO UPDATE SET pinned = 1, purged_at = NULL",
                (thread_id, _now_utc()),
            )
        else:
            cursor.execute(
                "INSERT INTO conversation_registry (thread_id, last_active, pinned) "
                "VALUES (?, ?, 0) "
                "ON CONFLICT(thread_id) DO UPDATE SET "
                "pinned = 0, last_active = excluded.last_active",
                (thread_id, _now_utc()),
            )
        connection.commit()
        cursor.execute(
            "SELECT * FROM conversation_registry WHERE thread_id = ?", (thread_id,)
        )
        row = cursor.fetchone()
        return _row_to_dict(row)
    finally:
        connection.close()


def list_active(limit: int = 500) -> list[dict[str, Any]]:
    """Conversations not (yet) purged, most recently active first."""
    connection = _get_connection()
    if connection is None:
        return []
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT * FROM conversation_registry WHERE purged_at IS NULL "
            "ORDER BY last_active DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
        return [_row_to_dict(row) for row in rows]
    finally:
        connection.close()


def list_purged(max_age_days: int = 30) -> list[str]:
    """Thread ids purged within the retention window.

    The web client deletes local conversations only for ids in this
    list, never based on a conversation being missing from list_active().
    Old tombstones age out via sweep_tombstones(), which keeps this list
    (and the /api/conversations payload) bounded.
    """
    connection = _get_connection()
    if connection is None:
        return []
    try:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=max_age_days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor = connection.cursor()
        cursor.execute(
            "SELECT thread_id FROM conversation_registry "
            "WHERE purged_at IS NOT NULL AND purged_at >= ? "
            "ORDER BY purged_at DESC",
            (cutoff,),
        )
        return [row["thread_id"] for row in cursor.fetchall()]
    finally:
        connection.close()


def count() -> int:
    connection = _get_connection()
    if connection is None:
        return 0
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM conversation_registry WHERE purged_at IS NULL"
        )
        return cursor.fetchone()[0]
    finally:
        connection.close()


def expired_candidates(ttl_seconds: int, limit: int = 50) -> list[str]:
    """Thread ids idle longer than ttl_seconds: unpinned, not already
    purged, oldest first, capped at `limit`.

    The cap matters as much as any throttling done by the caller: the
    purge runs under app/main.py's global store_lock, which serializes
    every conversation's turn pre-amble, so one uncapped pass after a long
    idle period would stall every other in-flight conversation behind a
    potentially huge deletion backlog. A capped list drains gradually,
    limit-per-pass, across however many turns it takes.
    """
    if ttl_seconds <= 0:
        return []
    connection = _get_connection()
    if connection is None:
        return []
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT thread_id FROM conversation_registry "
            "WHERE pinned = 0 AND purged_at IS NULL "
            "AND last_active < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?) "
            "ORDER BY last_active ASC LIMIT ?",
            (f"-{ttl_seconds} seconds", limit),
        )
        return [row["thread_id"] for row in cursor.fetchall()]
    finally:
        connection.close()


def mark_purged(thread_id: str) -> None:
    """Tombstone a conversation whose checkpoints were just deleted by the
    TTL purge. Also clears `pinned` defensively -- a pinned thread should
    never reach this path (expired_candidates excludes pinned rows), but
    the delete-conversation API route reuses this helper too, so leaving a
    stale pinned=1 on a tombstoned row would be confusing if it were ever
    resurrected by a future touch().
    """
    connection = _get_connection()
    if connection is None:
        return
    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE conversation_registry SET purged_at = ?, pinned = 0 "
            "WHERE thread_id = ?",
            (_now_utc(), thread_id),
        )
        connection.commit()
    finally:
        connection.close()


def forget(thread_id: str) -> None:
    """Hard-delete the registry row entirely.

    Used for explicit user-initiated deletion (DELETE /api/conversations),
    as opposed to the TTL purge path (mark_purged), which tombstones
    instead so the client can learn about it via the `purged` list. A
    user who explicitly deletes a conversation from the web client already
    knows it's gone -- there is no client-side cache to reconcile.
    """
    connection = _get_connection()
    if connection is None:
        return
    try:
        cursor = connection.cursor()
        cursor.execute(
            "DELETE FROM conversation_registry WHERE thread_id = ?", (thread_id,)
        )
        connection.commit()
    finally:
        connection.close()


def sweep_tombstones(max_age_days: int = 30) -> int:
    """Hard-delete tombstones older than the retention window so the table
    (and the `purged` list) doesn't grow forever."""
    connection = _get_connection()
    if connection is None:
        return 0
    try:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=max_age_days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor = connection.cursor()
        cursor.execute(
            "DELETE FROM conversation_registry "
            "WHERE purged_at IS NOT NULL AND purged_at < ?",
            (cutoff,),
        )
        deleted = cursor.rowcount
        connection.commit()
        return deleted
    finally:
        connection.close()


def reconcile(known_thread_ids: Iterable[str]) -> tuple[int, int]:
    """Bring the registry in line with what actually exists in
    rona_checkpoints.db. Called once at startup.

    - Inserts a row (last_active = now) for any thread id in
      known_thread_ids the registry has never seen, so pre-existing
      conversations -- including ones that predate this table, and ones
      orphaned by the old in-memory-only activity tracker across a
      restart -- become purgeable again instead of sitting forever as
      unpurgeable orphans.
    - Tombstones any unpinned, not-yet-purged row whose thread id is
      NOT in known_thread_ids: its checkpoints are already gone by some
      other means (e.g. rona_checkpoints.db was reset). Pinned rows are
      never touched by this branch, since a conversation can legitimately
      be pinned before its first backend turn exists.

    Returns (inserted, marked_purged).
    """
    connection = _get_connection()
    if connection is None:
        return (0, 0)
    try:
        known = set(known_thread_ids)
        cursor = connection.cursor()
        cursor.execute(
            "SELECT thread_id, pinned, purged_at FROM conversation_registry"
        )
        existing = {
            row["thread_id"]: (bool(row["pinned"]), row["purged_at"])
            for row in cursor.fetchall()
        }

        now = _now_utc()
        inserted = 0
        for thread_id in known - existing.keys():
            cursor.execute(
                "INSERT INTO conversation_registry (thread_id, last_active, pinned) "
                "VALUES (?, ?, 0)",
                (thread_id, now),
            )
            inserted += 1

        marked_purged = 0
        for thread_id, (pinned, purged_at) in existing.items():
            if pinned or purged_at is not None or thread_id in known:
                continue
            cursor.execute(
                "UPDATE conversation_registry SET purged_at = ? WHERE thread_id = ?",
                (now, thread_id),
            )
            marked_purged += 1

        connection.commit()
        return (inserted, marked_purged)
    finally:
        connection.close()
