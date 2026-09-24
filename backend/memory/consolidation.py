"""The consolidation engine: promotion, archiving and deletion of memories
by layer -- the automatic side of the "Konsolidasyon" system, run either
on a timer (memory/scheduler.py) or on demand (a CLI/API "run now").

Every step is gated by its own policy toggle and only ever moves a memory
one layer at a time in a single pass (a memory promoted short -> seasonal
this run has its layer_hits reset to 0, so it can't also clear the
seasonal -> deep threshold in the same pass). `deep` memories are never
selected by any step.

A single `threading.Lock` (`_run_lock`) makes sure the scheduler and a
manual run can never execute at the same time -- a second caller gets
`ConsolidationBusy` immediately instead of blocking on SQLite's write lock
or corrupting the run.

Import rule: see memory/__init__.py -- sibling modules are imported and
referenced as module objects (`memory_archive.archive_ids(...)`, not a
bare `archive_ids(...)`) so tests can monkeypatch them by attribute.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Any

import i18n
from memory import archive as memory_archive
from memory import clock as memory_clock
from memory import policy as memory_policy
from memory import runs as memory_runs
from memory import schema as memory_schema
from memory.policy import MemoryPolicy

logger = logging.getLogger("uvicorn.error")

_run_lock = threading.Lock()

_CHUNK = 500


class ConsolidationBusy(RuntimeError):
    """Raised by run_once() when another run already holds `_run_lock`."""


def is_running() -> bool:
    return _run_lock.locked()


def _chunks(ids: list[int], size: int = _CHUNK):
    for start in range(0, len(ids), size):
        yield ids[start : start + size]


def _preview(content: str, limit: int = 80) -> str:
    """Collapse `content` to a single line and cap it at `limit` chars,
    for a log line / report item -- never the full memory text."""
    collapsed = " ".join(content.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


def _item(row) -> dict:
    return {
        "id": row["id"],
        "layer": row["layer"],
        "hits": row["layer_hits"],
        "preview": _preview(row["content"]),
    }


def _consolidate(cursor, policy: MemoryPolicy, now: datetime) -> dict:
    """Run steps 0-4 against an already-open transaction on `cursor` and
    return the items each step touched. Called with the real database
    cursor for both real runs and dry runs alike -- run_once() decides
    afterwards whether to commit or roll the transaction back."""
    now_s = memory_clock.to_db(now)

    # Step 0: memories written before this package existed (or a legacy
    # row untouched since migration) have no layer_since yet -- start
    # their clock now rather than treating them as instantly overdue.
    cursor.execute(
        "UPDATE memories SET layer_since = ? "
        "WHERE layer_since IS NULL AND layer IN ('short', 'seasonal')",
        (now_s,),
    )

    promoted_short: list[dict] = []
    promoted_seasonal: list[dict] = []
    archived: list[dict] = []
    deleted: list[dict] = []

    # Step 1: short -> seasonal, for memories recalled often enough.
    if policy.auto_promote_enabled:
        rows = cursor.execute(
            "SELECT id, layer, layer_hits, content FROM memories "
            "WHERE layer = 'short' AND layer_hits >= ? ORDER BY id",
            (policy.short_promote_hits,),
        ).fetchall()
        promoted_short = [_item(row) for row in rows]
        for chunk in _chunks([row["id"] for row in rows]):
            placeholders = ",".join("?" for _ in chunk)
            cursor.execute(
                f"UPDATE memories SET layer = 'seasonal', layer_since = ?, layer_hits = 0 "
                f"WHERE id IN ({placeholders}) AND layer = 'short'",
                (now_s, *chunk),
            )

    # Step 2: seasonal -> deep. Rows promoted in step 1 have layer_hits
    # reset to 0, so they cannot also clear this threshold this run.
    if policy.auto_promote_enabled:
        rows = cursor.execute(
            "SELECT id, layer, layer_hits, content FROM memories "
            "WHERE layer = 'seasonal' AND layer_hits >= ? ORDER BY id",
            (policy.seasonal_promote_hits,),
        ).fetchall()
        promoted_seasonal = [_item(row) for row in rows]
        for chunk in _chunks([row["id"] for row in rows]):
            placeholders = ",".join("?" for _ in chunk)
            cursor.execute(
                f"UPDATE memories SET layer = 'deep', layer_since = ?, layer_hits = 0 "
                f"WHERE id IN ({placeholders}) AND layer = 'seasonal'",
                (now_s, *chunk),
            )

    # Step 3: archive seasonal memories that have sat idle too long. The
    # reference time is the later of last_accessed and layer_since (not
    # last_accessed alone) so a memory just promoted into seasonal isn't
    # instantly eligible because of a stale last_accessed carried over
    # from before the promotion.
    if policy.auto_archive_enabled:
        cutoff = memory_clock.to_db(now - timedelta(days=policy.seasonal_archive_days))
        rows = cursor.execute(
            "SELECT id, layer, layer_hits, content FROM memories "
            "WHERE layer = 'seasonal' "
            "AND MAX(COALESCE(last_accessed, layer_since), layer_since) < ? "
            "ORDER BY id",
            (cutoff,),
        ).fetchall()
        archived = [_item(row) for row in rows]
        ids = [row["id"] for row in rows]
        if ids:
            memory_archive.archive_ids(cursor, ids, reason="auto", now=now_s)

    # Step 4: delete short memories that are old and rarely recalled.
    if policy.auto_delete_enabled:
        cutoff = memory_clock.to_db(now - timedelta(days=policy.short_delete_days))
        rows = cursor.execute(
            "SELECT id, layer, layer_hits, content FROM memories "
            "WHERE layer = 'short' AND layer_since < ? AND layer_hits < ? "
            "ORDER BY id",
            (cutoff, policy.short_delete_below_hits),
        ).fetchall()
        deleted = [_item(row) for row in rows]
        for chunk in _chunks([row["id"] for row in rows]):
            placeholders = ",".join("?" for _ in chunk)
            cursor.execute(
                f"DELETE FROM memories WHERE id IN ({placeholders}) AND layer = 'short'",
                chunk,
            )

    return {
        "promoted_short": promoted_short,
        "promoted_seasonal": promoted_seasonal,
        "archived": archived,
        "deleted": deleted,
    }


def _record_failure(connection, *, triggered_by: str, started_at: str, error: str) -> None:
    """Record a failed run in its own short transaction, on top of a
    connection whose main transaction was just rolled back. Never raises
    -- a failure here must not mask the original exception."""
    try:
        if connection.in_transaction:
            connection.commit()
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.cursor()
        memory_runs.record(
            cursor,
            triggered_by=triggered_by,
            started_at=started_at,
            finished_at=memory_clock.to_db(memory_clock.utc_now()),
            counts={},
            error=error,
        )
        connection.commit()
    except Exception:  # noqa: BLE001
        connection.rollback()


def _log_run(triggered_by: str, items: dict, counts: dict) -> None:
    for item in items["promoted_short"]:
        logger.info(
            i18n.t("memory.log_promoted"),
            item["id"],
            "short",
            "seasonal",
            item["hits"],
            item["preview"],
        )
    for item in items["promoted_seasonal"]:
        logger.info(
            i18n.t("memory.log_promoted"),
            item["id"],
            "seasonal",
            "deep",
            item["hits"],
            item["preview"],
        )
    for item in items["archived"]:
        logger.info(
            i18n.t("memory.log_archived"),
            item["id"],
            item["layer"],
            "auto",
            item["preview"],
        )
    for item in items["deleted"]:
        logger.info(
            i18n.t("memory.log_deleted"),
            item["id"],
            item["hits"],
            item["preview"],
        )
    logger.info(
        i18n.t("memory.log_run_done"),
        triggered_by,
        counts["promoted_short"],
        counts["promoted_seasonal"],
        counts["archived"],
        counts["deleted"],
    )


def run_once(
    triggered_by: str = "manual",
    *,
    dry_run: bool = False,
    now: datetime | None = None,
    policy: MemoryPolicy | None = None,
) -> dict[str, Any]:
    """Run one consolidation pass and return a report describing what it
    did (or would do, for a dry run).

    `dry_run` runs the exact same `_consolidate()` inside the same
    `BEGIN IMMEDIATE` transaction as a real run and then rolls it back
    instead of committing, so the preview is never out of sync with what a
    real run would actually do. Nothing is persisted and no run row is
    recorded for a dry run.

    Raises `ConsolidationBusy` if another run already holds `_run_lock`.
    On any other failure the transaction is rolled back, a run row with
    the error is recorded (for a real run) in a fresh transaction, and the
    exception is re-raised after being logged.
    """
    if not _run_lock.acquire(blocking=False):
        raise ConsolidationBusy("a memory consolidation run is already in progress")
    try:
        policy = policy or memory_policy.current_policy()
        now = now or memory_clock.utc_now()
        started_at = memory_clock.to_db(memory_clock.utc_now())

        connection = memory_schema.connect()
        try:
            if connection.in_transaction:
                connection.commit()
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.cursor()
            try:
                items = _consolidate(cursor, policy, now)
            except Exception as exc:
                connection.rollback()
                if not dry_run:
                    _record_failure(
                        connection,
                        triggered_by=triggered_by,
                        started_at=started_at,
                        error=str(exc),
                    )
                logger.error(i18n.t("memory.log_run_failed"), triggered_by, exc)
                raise

            counts = {
                "promoted_short": len(items["promoted_short"]),
                "promoted_seasonal": len(items["promoted_seasonal"]),
                "archived": len(items["archived"]),
                "deleted": len(items["deleted"]),
            }
            finished_at = memory_clock.to_db(memory_clock.utc_now())

            if dry_run:
                connection.rollback()
                run_id = None
            else:
                run_id = memory_runs.record(
                    cursor,
                    triggered_by=triggered_by,
                    started_at=started_at,
                    finished_at=finished_at,
                    counts=counts,
                )
                connection.commit()
        finally:
            connection.close()
    finally:
        _run_lock.release()

    if not dry_run:
        _log_run(triggered_by, items, counts)

    return {
        "dry_run": dry_run,
        "triggered_by": triggered_by,
        "started_at": started_at,
        "finished_at": finished_at,
        "run_id": run_id,
        "policy": policy.as_dict(),
        "promoted_short": items["promoted_short"],
        "promoted_seasonal": items["promoted_seasonal"],
        "archived": items["archived"],
        "deleted": items["deleted"],
        "counts": counts,
    }
