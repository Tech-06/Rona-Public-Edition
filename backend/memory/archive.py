"""The memory archive: a holding table (`memory_archive`) for memories
that have been manually archived, auto-archived by consolidation, or
swept up when their linked person was deleted.

Archiving is a copy-then-delete out of `memories` inside the caller's own
transaction (or a dedicated one for the single-memory case): the archive
row keeps everything needed to bring the memory back later via
`restore()`, which always reconstitutes it as a `deep` memory with a
fresh layer clock. Nothing here is a dead end -- the archive is meant to
be recoverable, not a trash can that silently expires.

Import rule: see memory/__init__.py -- `memory_schema.connect()` imports
`toolbox.db` lazily, inside the function body.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence

from memory import clock as memory_clock
from memory import schema as memory_schema

REASONS = ("auto", "manual", "person_deleted")

_CHUNK = 500

# Destination columns in `memory_archive` and the matching source columns
# in `memories` -- same order, but the id column is named differently
# (`memory_id` vs `id`), so a copy needs both lists rather than one.
_ARCHIVE_COLUMNS = (
    "memory_id, person_id, layer, content, embedding, access_count, "
    "created_at, last_accessed, metadata"
)
_MEMORIES_COLUMNS = (
    "id, person_id, layer, content, embedding, access_count, "
    "created_at, last_accessed, metadata"
)


class NotFound(LookupError):
    """Raised when a memory or archive id doesn't exist."""


def _chunks(ids: Sequence[int], size: int = _CHUNK):
    for start in range(0, len(ids), size):
        yield ids[start : start + size]


def archive_ids(cursor: sqlite3.Cursor, ids: Sequence[int], *, reason: str, now: str) -> int:
    """Copy `ids` from `memories` into `memory_archive` (reason `reason`)
    then delete them from `memories`, in chunks of `_CHUNK`. Does not
    commit -- the caller owns the transaction. Returns how many rows were
    actually archived (an id that no longer exists is silently skipped)."""
    if reason not in REASONS:
        raise ValueError(f"invalid archive reason: {reason!r}")

    ids = list(ids)
    archived = 0
    for chunk in _chunks(ids):
        placeholders = ",".join("?" for _ in chunk)
        cursor.execute(
            f"""
            INSERT INTO memory_archive (
                {_ARCHIVE_COLUMNS}, archived_at, reason
            )
            SELECT {_MEMORIES_COLUMNS}, ?, ?
            FROM memories WHERE id IN ({placeholders})
            """,
            (now, reason, *chunk),
        )
        archived += cursor.rowcount
        cursor.execute(f"DELETE FROM memories WHERE id IN ({placeholders})", chunk)
    return archived


def archive_person_memories(
    cursor: sqlite3.Cursor, person_id: int, *, now: str | None = None
) -> int:
    """Archive every memory linked to `person_id` (reason `person_deleted`).
    Does not commit and does not log -- called from inside a person-delete
    transaction whose caller logs the outcome once, after commit."""
    now = now or memory_clock.to_db(memory_clock.utc_now())
    cursor.execute(
        f"""
        INSERT INTO memory_archive (
            {_ARCHIVE_COLUMNS}, archived_at, reason
        )
        SELECT {_MEMORIES_COLUMNS}, ?, 'person_deleted'
        FROM memories WHERE person_id = ?
        """,
        (now, person_id),
    )
    archived = cursor.rowcount
    cursor.execute("DELETE FROM memories WHERE person_id = ?", (person_id,))
    return archived


def archive_memory(memory_id: int, *, reason: str = "manual") -> int:
    """Archive a single memory in its own transaction. Returns the new
    `memory_archive` row id. Raises NotFound if the memory doesn't exist."""
    if reason not in REASONS:
        raise ValueError(f"invalid archive reason: {reason!r}")

    connection = memory_schema.connect()
    try:
        with memory_schema.immediate_transaction(connection):
            cursor = connection.cursor()
            exists = cursor.execute(
                "SELECT 1 FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
            if exists is None:
                raise NotFound(f"memory #{memory_id} not found")

            now = memory_clock.to_db(memory_clock.utc_now())
            cursor.execute(
                f"""
                INSERT INTO memory_archive (
                    {_ARCHIVE_COLUMNS}, archived_at, reason
                )
                SELECT {_MEMORIES_COLUMNS}, ?, ?
                FROM memories WHERE id = ?
                """,
                (now, reason, memory_id),
            )
            archive_id = cursor.lastrowid
            cursor.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        return archive_id
    finally:
        connection.close()


def list_archive(limit: int = 100, offset: int = 0) -> dict:
    """Page through the archive, newest first. Never returns the
    embedding blob -- callers only need it to display/restore/delete."""
    connection = memory_schema.connect()
    try:
        cursor = connection.cursor()
        total = cursor.execute("SELECT COUNT(*) FROM memory_archive").fetchone()[0]
        rows = cursor.execute(
            """
            SELECT id, memory_id, person_id, layer, content, access_count,
                   created_at, last_accessed, metadata, archived_at, reason
            FROM memory_archive
            ORDER BY archived_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        archive = [
            {
                "id": row["id"],
                "memory_id": row["memory_id"],
                "person_id": row["person_id"],
                "layer": row["layer"],
                "content": row["content"],
                "access_count": row["access_count"],
                "created_at": row["created_at"],
                "last_accessed": row["last_accessed"],
                "metadata": json.loads(row["metadata"] or "{}"),
                "archived_at": row["archived_at"],
                "reason": row["reason"],
            }
            for row in rows
        ]
        return {"archive": archive, "total": total}
    finally:
        connection.close()


def restore(archive_id: int) -> int:
    """Move an archived memory back into `memories` as a `deep` memory
    with a fresh layer clock (`layer_hits=0`, `layer_since=now`) and
    delete the archive row, all in one transaction.

    Content, embedding, created_at, metadata and access_count are carried
    over unchanged. The original memory id is reused when it is still free
    (AUTOINCREMENT never hands it out again, so it normally is); if it is
    taken anyway, a new id is assigned. `person_id` is kept only if
    it's NULL/0 (no link) or still points at an existing person; otherwise
    it's dropped to NULL rather than pointing at a person that no longer
    exists.
    """
    connection = memory_schema.connect()
    try:
        with memory_schema.immediate_transaction(connection):
            cursor = connection.cursor()
            row = cursor.execute(
                "SELECT * FROM memory_archive WHERE id = ?", (archive_id,)
            ).fetchone()
            if row is None:
                raise NotFound(f"archive #{archive_id} not found")

            person_id = row["person_id"]
            if person_id:
                still_exists = cursor.execute(
                    "SELECT 1 FROM people WHERE id = ?", (person_id,)
                ).fetchone()
                if still_exists is None:
                    person_id = None

            now = memory_clock.to_db(memory_clock.utc_now())
            id_taken = (
                cursor.execute(
                    "SELECT 1 FROM memories WHERE id = ?", (row["memory_id"],)
                ).fetchone()
                is not None
            )

            if id_taken:
                cursor.execute(
                    """
                    INSERT INTO memories (
                        person_id, layer, content, embedding, access_count,
                        created_at, last_accessed, metadata, layer_since, layer_hits
                    ) VALUES (?, 'deep', ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        person_id,
                        row["content"],
                        row["embedding"],
                        row["access_count"],
                        row["created_at"],
                        row["last_accessed"],
                        row["metadata"],
                        now,
                    ),
                )
                memory_id = cursor.lastrowid
            else:
                cursor.execute(
                    """
                    INSERT INTO memories (
                        id, person_id, layer, content, embedding, access_count,
                        created_at, last_accessed, metadata, layer_since, layer_hits
                    ) VALUES (?, ?, 'deep', ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        row["memory_id"],
                        person_id,
                        row["content"],
                        row["embedding"],
                        row["access_count"],
                        row["created_at"],
                        row["last_accessed"],
                        row["metadata"],
                        now,
                    ),
                )
                memory_id = row["memory_id"]

            cursor.execute("DELETE FROM memory_archive WHERE id = ?", (archive_id,))
        return memory_id
    finally:
        connection.close()


def delete_archived(archive_id: int) -> None:
    """Permanently delete an archive row. Raises NotFound if it doesn't
    exist."""
    connection = memory_schema.connect()
    try:
        cursor = connection.cursor()
        cursor.execute("DELETE FROM memory_archive WHERE id = ?", (archive_id,))
        if cursor.rowcount == 0:
            raise NotFound(f"archive #{archive_id} not found")
        connection.commit()
    finally:
        connection.close()


def count() -> int:
    connection = memory_schema.connect()
    try:
        return connection.execute("SELECT COUNT(*) FROM memory_archive").fetchone()[0]
    finally:
        connection.close()
