"""Persistent history of consolidation runs (`memory_consolidation_runs`),
kept so the web dashboard and CLI can show what the last automatic (or
manual) pass actually did, and so memory/scheduler.py can tell when the
next one is due without keeping its own state across restarts.

Only the last `KEEP_RUNS` rows are kept -- this is an operational log, not
an audit trail, and an unbounded table would just grow forever on a
system that's been running for months.

Import rule: see memory/__init__.py -- `memory_schema.connect()` /
`connect_if_exists()` import `toolbox.db` lazily, inside the function
body.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from memory import clock as memory_clock
from memory import schema as memory_schema

KEEP_RUNS = 50

_COUNT_FIELDS = ("promoted_short", "promoted_seasonal", "archived", "deleted")


def record(
    cursor: sqlite3.Cursor,
    *,
    triggered_by: str,
    started_at: str,
    finished_at: str,
    counts: dict,
    error: str | None = None,
) -> int:
    """Insert one run row and prune anything past `KEEP_RUNS`. Does not
    commit -- the caller owns the transaction. Returns the new row id."""
    cursor.execute(
        """
        INSERT INTO memory_consolidation_runs (
            triggered_by, started_at, finished_at,
            promoted_short, promoted_seasonal, archived, deleted, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            triggered_by,
            started_at,
            finished_at,
            *(counts.get(field, 0) for field in _COUNT_FIELDS),
            error,
        ),
    )
    run_id = cursor.lastrowid
    cursor.execute(
        """
        DELETE FROM memory_consolidation_runs
        WHERE id NOT IN (
            SELECT id FROM memory_consolidation_runs ORDER BY id DESC LIMIT ?
        )
        """,
        (KEEP_RUNS,),
    )
    return run_id


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "triggered_by": row["triggered_by"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "promoted_short": row["promoted_short"],
        "promoted_seasonal": row["promoted_seasonal"],
        "archived": row["archived"],
        "deleted": row["deleted"],
        "error": row["error"],
    }


def list_recent(limit: int = 10) -> list[dict]:
    connection = memory_schema.connect_if_exists()
    if connection is None:
        return []
    try:
        rows = connection.execute(
            "SELECT * FROM memory_consolidation_runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]
    finally:
        connection.close()


def last_run() -> dict | None:
    connection = memory_schema.connect_if_exists()
    if connection is None:
        return None
    try:
        row = connection.execute(
            "SELECT * FROM memory_consolidation_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return _row_to_dict(row) if row is not None else None
    finally:
        connection.close()


def last_finished_at() -> datetime | None:
    run = last_run()
    if run is None:
        return None
    return memory_clock.from_db(run["finished_at"])
