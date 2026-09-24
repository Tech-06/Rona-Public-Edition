"""Access tracking for recalled memories.

Only Rona's own `search_memories` tool call counts as a "recall" -- never
a web dashboard or CLI lookup, and never a plain `get_memories` listing.
The counting itself lives here as two small, independently testable
pieces so `toolbox/tools/mem_tool.py` (which owns the LLM-facing
`search_memories` signature) can stay thin:

- `counted_ids()` picks which of a search's result ids are even eligible
  to be counted (the top N, de-duplicated).
- `record_hits()` applies the actual, atomic database update, including
  the per-memory cooldown that keeps several `search_memories` calls
  inside one turn (Rona routinely fires a handful in parallel to recall
  thoroughly) from counting the same memory more than once.

Stdlib only -- see memory/__init__.py's import rule.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import datetime, timedelta

from memory.clock import to_db


def counted_ids(result_ids: Sequence[int], top_n: int) -> list[int]:
    """The first `top_n` ids from `result_ids`, de-duplicated and in their
    original order. `top_n < 1` (including 0 and negative) yields no ids.
    """
    if top_n < 1:
        return []
    seen: set[int] = set()
    counted: list[int] = []
    for memory_id in result_ids:
        if memory_id in seen:
            continue
        seen.add(memory_id)
        counted.append(memory_id)
        if len(counted) >= top_n:
            break
    return counted


def record_hits(
    connection: sqlite3.Connection,
    memory_ids: Sequence[int],
    *,
    now: datetime,
    cooldown_hours: int,
) -> int:
    """Count a recall for each id in `memory_ids` that is off cooldown.

    A single atomic `UPDATE ... WHERE id IN (...) AND (...)` statement so
    that parallel `search_memories` calls within one turn -- each running
    its own SELECT-then-UPDATE -- still only count a given memory once:
    whichever UPDATE commits first moves `last_accessed` to `now`, and any
    other call for the same id in the same cooldown window then fails the
    `last_accessed <= :cutoff` check.

    `last_accessed` therefore means "time of the last *counted* access",
    not "time of the last search that returned this memory". With
    `cooldown_hours=0` the cutoff equals `now`, so every call counts.

    Returns 0 without touching the database if `memory_ids` is empty.
    """
    if not memory_ids:
        return 0

    cutoff = now - timedelta(hours=cooldown_hours)
    placeholders = ", ".join("?" * len(memory_ids))
    # The id list is inherently positional (a variable-length `IN (...)`),
    # and sqlite3 doesn't allow mixing named and positional placeholders in
    # one statement, so `now`/`cutoff` are bound positionally too, in the
    # order they appear in the SQL text below.
    cursor = connection.execute(
        f"""
        UPDATE memories
        SET access_count = access_count + 1,
            layer_hits = layer_hits + 1,
            last_accessed = ?
        WHERE id IN ({placeholders})
          AND (last_accessed IS NULL OR last_accessed <= ?)
        """,
        [to_db(now), *memory_ids, to_db(cutoff)],
    )
    connection.commit()
    return cursor.rowcount
