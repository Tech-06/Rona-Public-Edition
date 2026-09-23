"""Durable, server-side chat history shared by every client that connects
to this backend -- the point being that a phone and a desktop browser (or
two browsers on two different addresses, e.g. before/after switching to a
Tailscale HTTPS hostname) see the *same* conversation list and messages,
instead of each keeping its own copy in localStorage.

Persisted in the backend's own `rona.db` (via toolbox.db), the same file
`graph.conversations` already uses for the pin/TTL registry. That registry
stays the single source of truth for *pinned* and for TTL purge timing --
this module only stores what the old client-side storage.ts used to keep
in localStorage: titles, folder assignment, and the message transcript
itself. `list_index()`/`get()`/`export_all()` read pin state from
`graph.conversations` rather than duplicating it, so pinning (already
synced immediately by ConversationRow's toggle -- see
`POST /api/conversations/{id}/pin`) never has two disagreeing copies.

Every conversation row here is expected to have a matching
`conversation_registry` row, because `record_turn()` is only ever called
from `app/main.py`'s `_stream_worker` *after* `_run_turn()` has already
called `touch()` on that thread_id. `import_conversations()` (the one-time
localStorage-migration path) restores that invariant explicitly by calling
`touch()` itself for everything it imports.

Like graph.conversations, every function here self-heals the schema on
each call and degrades to a no-op (or an empty result) if rona.db doesn't
exist yet, so importing this module never requires rona.db to be present.
"""

import json
import sqlite3
import time
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from graph import conversations
from toolbox import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_history (
    thread_id    TEXT PRIMARY KEY,
    title        TEXT NOT NULL DEFAULT '',
    title_custom INTEGER NOT NULL DEFAULT 0,
    folder_id    TEXT,
    messages     TEXT NOT NULL DEFAULT '[]',
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL
)
"""

FOLDERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_folders (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    collapsed  INTEGER NOT NULL DEFAULT 0
)
"""

INDEX = "CREATE INDEX IF NOT EXISTS idx_chat_history_folder ON chat_history(folder_id)"


def _apply_schema(connection: sqlite3.Connection) -> None:
    cursor = connection.cursor()
    cursor.execute(SCHEMA)
    cursor.execute(FOLDERS_SCHEMA)
    cursor.execute(INDEX)
    connection.commit()


def _get_connection() -> sqlite3.Connection | None:
    connection = db.connect_if_exists()
    if connection is None:
        return None
    try:
        _apply_schema(connection)
    except sqlite3.Error:
        pass
    return connection


def ensure_schema() -> None:
    """Create the tables/index if missing. See conversations.ensure_schema()
    -- every function here already self-heals on every call, so this is
    mostly an explicit early call site for app startup."""
    connection = _get_connection()
    if connection is None:
        return
    connection.close()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _title_from_message(message: dict[str, Any]) -> str:
    content = str(message.get("content") or "").strip()
    return content[:60]


def _folder_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
        "collapsed": bool(row["collapsed"]),
    }


class TurnRecorder:
    """Wraps a `StreamRun` (app/streaming.py) so `_run_turn`'s `sink.publish()`
    calls keep flowing to the live SSE subscribers exactly as before, while
    also building the `steps` list that gets persisted alongside the
    assistant's message.

    This duplicates -- deliberately -- the bookkeeping useChat.ts's
    handleProgress() used to do client-side (see
    web-client/frontend/src/hooks/useChat.ts): with the transcript now
    written server-side, it has to be computed once here instead, so every
    client sees the same step list whether or not it was present for the
    live stream.

    Only duck-types `.publish(event_type, data)` -- deliberately not
    importing app.streaming.StreamRun's type, since `graph` sits below
    `app` in this codebase's layering and must not import from it.
    """

    def __init__(self, run: Any | None) -> None:
        self._run = run
        self.steps: list[dict[str, Any]] = []

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        if self._run is not None:
            self._run.publish(event_type, data)
        if event_type != "progress":
            return
        kind = data.get("type")
        if kind == "tool_start" and data.get("call_id") and data.get("name"):
            self.steps.append(
                {
                    "callId": data["call_id"],
                    "name": data["name"],
                    "args": data.get("args") or {},
                    "status": "running",
                    "durationMs": None,
                }
            )
        elif kind == "tool_end" and data.get("call_id"):
            for step in self.steps:
                if step["callId"] == data["call_id"]:
                    step["status"] = data.get("status", "ok")
                    step["durationMs"] = data.get("duration_ms")
                    break


def record_turn(
    thread_id: str,
    user_message: dict[str, Any],
    assistant_message: dict[str, Any],
) -> None:
    """Append one user+assistant message pair, upserting the conversation's
    row. Mirrors the old client-side saveConversation()
    (web-client/frontend/src/lib/storage.ts): the title is derived from the
    first user message once, then frozen the moment it's custom (renamed)
    so a later turn never overwrites a name the user chose.

    Silently does nothing if rona.db isn't available -- a chat still works
    without a persisted transcript, it just won't show up in any client's
    conversation list.
    """
    connection = _get_connection()
    if connection is None:
        return
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT title, title_custom, messages, created_at "
            "FROM chat_history WHERE thread_id = ?",
            (thread_id,),
        )
        row = cursor.fetchone()
        now = _now_ms()
        if row is None:
            messages: list[dict[str, Any]] = []
            title = _title_from_message(user_message)
            created_at = now
        else:
            messages = json.loads(row["messages"] or "[]")
            title = (
                row["title"]
                if row["title_custom"]
                else (row["title"] or _title_from_message(user_message))
            )
            created_at = row["created_at"]
        messages.append(user_message)
        messages.append(assistant_message)
        cursor.execute(
            "INSERT INTO chat_history "
            "(thread_id, title, title_custom, messages, created_at, updated_at) "
            "VALUES (?, ?, 0, ?, ?, ?) "
            "ON CONFLICT(thread_id) DO UPDATE SET "
            "title = excluded.title, messages = excluded.messages, "
            "updated_at = excluded.updated_at",
            (thread_id, title, json.dumps(messages, ensure_ascii=False), created_at, now),
        )
        connection.commit()
    finally:
        connection.close()


def list_index(limit: int = 500) -> list[dict[str, Any]]:
    """Conversation summaries (no messages), most recently updated first,
    with `pinned` filled in from graph.conversations."""
    connection = _get_connection()
    if connection is None:
        return []
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT thread_id, title, title_custom, folder_id, updated_at "
            "FROM chat_history ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
    finally:
        connection.close()
    pinned_ids = {
        row["thread_id"] for row in conversations.list_active(limit=10_000) if row["pinned"]
    }
    return [
        {
            "thread_id": row["thread_id"],
            "title": row["title"],
            "title_custom": bool(row["title_custom"]),
            "folder_id": row["folder_id"],
            "updated_at": row["updated_at"],
            "pinned": row["thread_id"] in pinned_ids,
        }
        for row in rows
    ]


def get(thread_id: str) -> dict[str, Any] | None:
    """One conversation, including its full message transcript."""
    connection = _get_connection()
    if connection is None:
        return None
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM chat_history WHERE thread_id = ?", (thread_id,))
        row = cursor.fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    registry_row = conversations.get(thread_id)
    return {
        "thread_id": row["thread_id"],
        "title": row["title"],
        "title_custom": bool(row["title_custom"]),
        "folder_id": row["folder_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "pinned": bool(registry_row["pinned"]) if registry_row else False,
        "messages": json.loads(row["messages"] or "[]"),
    }


def rename(thread_id: str, title: str) -> bool:
    """Set an explicit title, freezing it against future auto-derivation
    from the first message (mirrors renameConversation() in storage.ts).
    Returns False for a blank title or an unknown thread_id."""
    trimmed = title.strip()
    if not trimmed:
        return False
    connection = _get_connection()
    if connection is None:
        return False
    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE chat_history SET title = ?, title_custom = 1 WHERE thread_id = ?",
            (trimmed, thread_id),
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def set_folder(thread_id: str, folder_id: str | None) -> bool:
    """Mirrors setConversationFolder() in storage.ts. `folder_id=None`
    un-files the conversation."""
    connection = _get_connection()
    if connection is None:
        return False
    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE chat_history SET folder_id = ? WHERE thread_id = ?",
            (folder_id, thread_id),
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def delete(thread_id: str) -> None:
    connection = _get_connection()
    if connection is None:
        return
    try:
        connection.execute("DELETE FROM chat_history WHERE thread_id = ?", (thread_id,))
        connection.commit()
    finally:
        connection.close()


def delete_all(except_ids: Iterable[str] = ()) -> int:
    """Deletes every conversation except the given ids (used to skip ones
    that are mid-turn -- see app/dashboard.py's delete_all_conversations,
    which already skips those for the checkpoint/registry deletion for the
    same reason). Returns the number of rows deleted."""
    connection = _get_connection()
    if connection is None:
        return 0
    try:
        skip = set(except_ids)
        cursor = connection.cursor()
        if skip:
            placeholders = ",".join("?" for _ in skip)
            cursor.execute(
                f"DELETE FROM chat_history WHERE thread_id NOT IN ({placeholders})",
                tuple(skip),
            )
        else:
            cursor.execute("DELETE FROM chat_history")
        deleted = cursor.rowcount
        connection.commit()
        return deleted
    finally:
        connection.close()


def list_folders() -> list[dict[str, Any]]:
    connection = _get_connection()
    if connection is None:
        return []
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM chat_folders ORDER BY created_at ASC")
        rows = cursor.fetchall()
        return [_folder_row(row) for row in rows]
    finally:
        connection.close()


def create_folder(name: str) -> dict[str, Any] | None:
    trimmed = name.strip()
    connection = _get_connection()
    if connection is None:
        return None
    try:
        folder_id = f"folder-{uuid.uuid4().hex[:12]}"
        now = _now_ms()
        connection.execute(
            "INSERT INTO chat_folders (id, name, created_at, collapsed) VALUES (?, ?, ?, 0)",
            (folder_id, trimmed, now),
        )
        connection.commit()
        return {"id": folder_id, "name": trimmed, "created_at": now, "collapsed": False}
    finally:
        connection.close()


def rename_folder(folder_id: str, name: str) -> bool:
    trimmed = name.strip()
    if not trimmed:
        return False
    connection = _get_connection()
    if connection is None:
        return False
    try:
        cursor = connection.cursor()
        cursor.execute("UPDATE chat_folders SET name = ? WHERE id = ?", (trimmed, folder_id))
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def set_folder_collapsed(folder_id: str, collapsed: bool) -> bool:
    connection = _get_connection()
    if connection is None:
        return False
    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE chat_folders SET collapsed = ? WHERE id = ?",
            (int(collapsed), folder_id),
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def delete_folder(folder_id: str) -> bool:
    """Un-files every conversation in the folder instead of deleting them
    -- deleting a folder must never delete chats (mirrors deleteFolder() in
    storage.ts)."""
    connection = _get_connection()
    if connection is None:
        return False
    try:
        cursor = connection.cursor()
        cursor.execute("DELETE FROM chat_folders WHERE id = ?", (folder_id,))
        existed = cursor.rowcount > 0
        cursor.execute(
            "UPDATE chat_history SET folder_id = NULL WHERE folder_id = ?", (folder_id,)
        )
        connection.commit()
        return existed
    finally:
        connection.close()


def delete_all_folders() -> int:
    connection = _get_connection()
    if connection is None:
        return 0
    try:
        cursor = connection.cursor()
        cursor.execute("DELETE FROM chat_folders")
        deleted = cursor.rowcount
        connection.commit()
        return deleted
    finally:
        connection.close()


def export_all() -> dict[str, Any]:
    """Mirrors the old client-side exportAll()'s `ConversationExport` shape
    exactly (web-client/frontend/src/lib/storage.ts's TS interface of the
    same name), so the web client's "export all chats" button needs no
    format change on the frontend -- just a different (server-side) source
    of truth."""
    connection = _get_connection()
    if connection is None:
        return {"exportedAt": datetime.now(timezone.utc).isoformat(), "conversations": []}
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM chat_history ORDER BY updated_at DESC")
        rows = cursor.fetchall()
    finally:
        connection.close()
    pinned_ids = {
        row["thread_id"] for row in conversations.list_active(limit=10_000) if row["pinned"]
    }
    return {
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "conversations": [
            {
                "conversationId": row["thread_id"],
                "title": row["title"],
                "updatedAt": row["updated_at"],
                "pinned": row["thread_id"] in pinned_ids,
                "folderId": row["folder_id"],
                "messages": json.loads(row["messages"] or "[]"),
            }
            for row in rows
        ],
    }


def import_conversations(
    conversations_in: list[dict[str, Any]],
    folders_in: list[dict[str, Any]],
) -> dict[str, int]:
    """One-time migration path for the pre-server localStorage format
    (web-client/frontend/src/lib/storage.ts's old per-origin STORAGE_KEY /
    FOLDERS_KEY shape, one call per device being migrated).

    Only ever ADDS conversations/folders that don't already exist
    server-side -- never overwrites -- so importing from a second device
    can't clobber history a first device already migrated, and importing
    the same device's export twice is a harmless no-op.

    `conversations_in` items: {conversationId, title, titleCustom,
    updatedAt, pinned, folderId, messages}.
    `folders_in` items: {id, name, createdAt, collapsed}.

    Every imported conversation is touch()ed in graph.conversations so it
    gets a registry row and re-enters the normal TTL/purge lifecycle,
    exactly like conversations.reconcile() does for pre-registry
    conversations at startup -- otherwise it would sit as a permanent,
    unpurgeable orphan the registry has never seen.
    """
    connection = _get_connection()
    if connection is None:
        return {"conversations_imported": 0, "folders_imported": 0}
    imported_thread_ids: list[str] = []
    pins_to_apply: list[str] = []
    try:
        cursor = connection.cursor()

        folders_imported = 0
        for folder in folders_in:
            folder_id = str(folder.get("id") or "").strip()
            name = str(folder.get("name") or "").strip()
            if not folder_id or not name:
                continue
            cursor.execute("SELECT 1 FROM chat_folders WHERE id = ?", (folder_id,))
            if cursor.fetchone() is not None:
                continue
            cursor.execute(
                "INSERT INTO chat_folders (id, name, created_at, collapsed) VALUES (?, ?, ?, ?)",
                (
                    folder_id,
                    name,
                    int(folder.get("createdAt") or _now_ms()),
                    int(bool(folder.get("collapsed"))),
                ),
            )
            folders_imported += 1

        conversations_imported = 0
        for conv in conversations_in:
            thread_id = str(conv.get("conversationId") or "").strip()
            if not thread_id:
                continue
            cursor.execute("SELECT 1 FROM chat_history WHERE thread_id = ?", (thread_id,))
            if cursor.fetchone() is not None:
                continue
            now = _now_ms()
            title = str(conv.get("title") or "").strip()
            messages = conv.get("messages")
            if not isinstance(messages, list):
                messages = []
            updated_at = int(conv.get("updatedAt") or now)
            cursor.execute(
                "INSERT INTO chat_history "
                "(thread_id, title, title_custom, folder_id, messages, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    thread_id,
                    title,
                    int(bool(conv.get("titleCustom"))),
                    conv.get("folderId"),
                    json.dumps(messages, ensure_ascii=False),
                    updated_at,
                    updated_at,
                ),
            )
            conversations_imported += 1
            imported_thread_ids.append(thread_id)
            if conv.get("pinned"):
                pins_to_apply.append(thread_id)

        connection.commit()
    finally:
        connection.close()

    for thread_id in imported_thread_ids:
        conversations.touch(thread_id)
    for thread_id in pins_to_apply:
        conversations.set_pinned(thread_id, True)

    return {
        "conversations_imported": conversations_imported,
        "folders_imported": folders_imported,
    }
