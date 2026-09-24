"""DDL and self-healing migration for the memory consolidation package.

Adds two columns to the existing `memories` table (`layer_since`,
`layer_hits`) plus two new tables (`memory_archive`,
`memory_consolidation_runs`), following the same self-healing pattern as
`graph/conversations.py`: every statement is idempotent (`IF NOT EXISTS`
/ a `PRAGMA table_info` guard around each `ALTER TABLE ... ADD COLUMN`),
and `apply_schema()` is safe to call any number of times, on a brand new
database or a years-old one.

Only SQLite features available in SQLite >= 3.24 are used here (no
`RETURNING`, no `UPDATE ... FROM`, no `DROP COLUMN`) since the deployed
system SQLite may be older than whatever ships with a dev machine.

Import rule: see memory/__init__.py. `connect()`/`connect_if_exists()`
import `toolbox.db` lazily, inside the function body, specifically so
this module (and `mem_tool.py`, which calls into it) never creates a
module-level cycle back into `toolbox`.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
import threading
from datetime import datetime

import i18n
from memory.clock import to_db, utc_now

# -- DDL -----------------------------------------------------------------

# (column name, declaration) -- applied in this order.
MEMORY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("layer_since", "TEXT"),
    ("layer_hits", "INTEGER NOT NULL DEFAULT 0"),
)

MEMORIES_LAYER_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_memories_layer ON memories(layer)"
)

ARCHIVE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS memory_archive (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id INTEGER NOT NULL,
    person_id INTEGER,
    layer TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding BLOB NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_accessed TEXT,
    metadata TEXT DEFAULT '{}',
    archived_at TEXT NOT NULL,
    reason TEXT NOT NULL
)
"""

ARCHIVE_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_memory_archive_archived_at "
    "ON memory_archive(archived_at)"
)

RUNS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS memory_consolidation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    triggered_by TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    promoted_short INTEGER NOT NULL DEFAULT 0,
    promoted_seasonal INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0,
    error TEXT
)
"""

# Consumed by create_db.py as its v3 migration.
MIGRATION_STATEMENTS: tuple[str, ...] = (ARCHIVE_TABLE_SQL, ARCHIVE_INDEX_SQL, RUNS_TABLE_SQL)


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    cursor = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return cursor.fetchone() is not None


def apply_schema(connection: sqlite3.Connection, *, now: datetime | None = None) -> list[str]:
    """Create/upgrade everything this module owns on `connection`.

    Returns the list of `memories` columns that were actually added (empty
    if the schema was already current). Safe to call repeatedly.

    `now` lets callers (mainly tests) pin the backfill time for
    `layer_since`. It is deliberately NOT `created_at`: backfilling with
    the migration time means an upgrade never makes a pre-existing memory
    immediately eligible for short-layer deletion or seasonal archiving --
    those clocks only start ticking from the moment this ran.
    """
    cursor = connection.cursor()
    for statement in MIGRATION_STATEMENTS:
        cursor.execute(statement)

    added: list[str] = []
    if _table_exists(connection, "memories"):
        cursor.execute("PRAGMA table_info(memories)")
        # Column name is index 1 whether a row comes back as a plain tuple
        # (create_db.py's bare sqlite3 connection) or as a sqlite3.Row
        # (toolbox.db's connections) -- both support integer indexing.
        existing_columns = {row[1] for row in cursor.fetchall()}
        for name, declaration in MEMORY_COLUMNS:
            if name not in existing_columns:
                cursor.execute(f"ALTER TABLE memories ADD COLUMN {name} {declaration}")
                added.append(name)

        if "layer_since" in added:
            cursor.execute(
                "UPDATE memories SET layer_since = ? WHERE layer_since IS NULL",
                (to_db(now or utc_now()),),
            )

        cursor.execute(MEMORIES_LAYER_INDEX_SQL)

    connection.commit()
    return added


# -- Self-healing connect helpers -----------------------------------------

_healed_paths: set[str] = set()
_heal_lock = threading.Lock()


def _reset_heal_cache() -> None:
    """Test-only: forget which database paths have already been repaired."""
    with _heal_lock:
        _healed_paths.clear()


def _heal_if_needed(connection: sqlite3.Connection, db_path: object) -> None:
    key = str(db_path)
    with _heal_lock:
        if key in _healed_paths:
            return
        try:
            apply_schema(connection)
        except sqlite3.Error as exc:
            logging.getLogger("uvicorn.error").error(i18n.t("memory.log_schema_failed"), exc)
            return
        _healed_paths.add(key)


def connect() -> sqlite3.Connection:
    """Like `toolbox.db.connect()`, but repairs this package's schema on
    the first connection to a given database path."""
    from toolbox import db

    connection = db.connect()
    _heal_if_needed(connection, db.DB_PATH)
    return connection


def connect_if_exists() -> sqlite3.Connection | None:
    """Like `toolbox.db.connect_if_exists()`, but repairs this package's
    schema on the first connection to a given database path. Returns None
    (and never creates the file) if the database doesn't exist yet."""
    from toolbox import db

    connection = db.connect_if_exists()
    if connection is None:
        return None
    _heal_if_needed(connection, db.DB_PATH)
    return connection


def ensure_schema() -> None:
    """Run the migration once, eagerly, at app startup.

    Mirrors `graph/conversations.py`'s `ensure_schema()`: every function
    that reaches the database through `connect()`/`connect_if_exists()`
    already self-heals on first use, so this call is mostly about paying
    that one-time cost before the first real request instead of during
    it, and about logging the upgrade once, clearly, at startup.

    Does nothing (and creates no file) if rona.db doesn't exist yet.
    Any sqlite3.Error is logged and swallowed -- a broken schema check
    must never prevent the app from starting.
    """
    from toolbox import db

    connection = db.connect_if_exists()
    if connection is None:
        return
    try:
        added = apply_schema(connection)
        if added:
            logging.getLogger("uvicorn.error").info(
                i18n.t("memory.log_schema_upgraded"), ", ".join(added)
            )
        with _heal_lock:
            _healed_paths.add(str(db.DB_PATH))
    except sqlite3.Error as exc:
        logging.getLogger("uvicorn.error").error(i18n.t("memory.log_schema_failed"), exc)
    finally:
        connection.close()


@contextlib.contextmanager
def immediate_transaction(connection: sqlite3.Connection):
    """Run a block of statements inside `BEGIN IMMEDIATE`, committing on
    success and rolling back (then re-raising) on any exception.

    `BEGIN IMMEDIATE` takes SQLite's write lock up front instead of on the
    first write, so a multi-statement read-then-write block (archiving,
    restoring, deleting a person) sees a consistent snapshot and never
    hits a late `SQLITE_BUSY` halfway through.

    Connections here use Python's default (legacy) isolation mode, which
    can leave an implicit transaction open from a previous statement; a
    bare `BEGIN IMMEDIATE` on top of that raises "cannot start a
    transaction within a transaction", so any pending transaction is
    committed first.
    """
    if connection.in_transaction:
        connection.commit()
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()
