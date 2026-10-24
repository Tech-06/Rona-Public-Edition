import sqlite3

from memory import schema as memory_schema
from toolbox.db import DB_PATH, restrict_permissions

INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_task_runs_task_id ON task_runs(task_id)",
    (
        "CREATE INDEX IF NOT EXISTS idx_task_runs_status_reported "
        "ON task_runs(status, reported)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_subagent_runs_status_reported "
        "ON subagent_runs(status, reported)"
    ),
    "CREATE INDEX IF NOT EXISTS idx_memories_person_id ON memories(person_id)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)",
    "CREATE INDEX IF NOT EXISTS idx_memories_layer ON memories(layer)",
)

def _add_embedding_model_column(cursor: sqlite3.Cursor) -> None:
    # Guarded because mem_tool self-heals this column at runtime on a
    # database that hasn't been migrated yet; a bare ALTER would then fail.
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(memories)")}
    if "embedding_model" not in columns:
        cursor.execute("ALTER TABLE memories ADD COLUMN embedding_model TEXT")


def _add_source_column(cursor: sqlite3.Cursor) -> None:
    # Guarded for the same reason as above: mem_tool self-heals it too.
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(memories)")}
    if "source" not in columns:
        cursor.execute("ALTER TABLE memories ADD COLUMN source TEXT")


def _add_task_run_column(cursor: sqlite3.Cursor, column: str, column_type: str) -> None:
    # Guarded because trigger.store self-heals these columns at runtime on a
    # database that hasn't been migrated yet; a bare ALTER would then fail.
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(task_runs)")}
    if column not in columns:
        cursor.execute(f"ALTER TABLE task_runs ADD COLUMN {column} {column_type}")


def _add_action_done_at_column(cursor: sqlite3.Cursor) -> None:
    _add_task_run_column(cursor, "action_done_at", "TEXT")


def _add_executed_calls_column(cursor: sqlite3.Cursor) -> None:
    _add_task_run_column(cursor, "executed_calls", "TEXT")


# A migration step is either a SQL statement or a callable taking the cursor.
MIGRATIONS: list[tuple[int, tuple[object, ...]]] = [
    (
        1,
        (
            # Mirrors graph/conversations.py's SCHEMA/INDEX as a literal.
            # (This script is not actually independent of `app`: importing
            # toolbox.db runs toolbox/__init__.py, whose registry loads
            # app.config.) Both copies use IF NOT EXISTS, so any drift
            # between them is harmless: graph.conversations.ensure_schema()
            # also runs at every app startup regardless of this migration.
            """
            CREATE TABLE IF NOT EXISTS conversation_registry (
                thread_id   TEXT PRIMARY KEY,
                last_active TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                pinned      INTEGER NOT NULL DEFAULT 0,
                purged_at   TEXT
            )
            """,
            (
                "CREATE INDEX IF NOT EXISTS idx_conversation_registry_scan "
                "ON conversation_registry(pinned, purged_at, last_active)"
            ),
        ),
    ),
    (
        2,
        (
            # Mirrors graph/history.py's SCHEMA/FOLDERS_SCHEMA/INDEX, literal
            # for the same self-heal-parity reason as migration 1 above.
            # graph.history.ensure_schema() also self-heals this at every
            # app startup regardless of whether this migration ran.
            """
            CREATE TABLE IF NOT EXISTS chat_history (
                thread_id    TEXT PRIMARY KEY,
                title        TEXT NOT NULL DEFAULT '',
                title_custom INTEGER NOT NULL DEFAULT 0,
                folder_id    TEXT,
                messages     TEXT NOT NULL DEFAULT '[]',
                created_at   INTEGER NOT NULL,
                updated_at   INTEGER NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS chat_folders (
                id         TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                collapsed  INTEGER NOT NULL DEFAULT 0
            )
            """,
            (
                "CREATE INDEX IF NOT EXISTS idx_chat_history_folder "
                "ON chat_history(folder_id)"
            ),
        ),
    ),
    (
        # Imported from memory/schema.py (stdlib-only) rather than repeated
        # as a literal. memory.schema also self-heals on first connect(),
        # so this mainly records the schema version for fresh databases.
        3,
        memory_schema.MIGRATION_STATEMENTS,
    ),
    (
        # Set once a run's pre-approved action has executed successfully, so
        # retry attempts (and a restarted attempt) never repeat a side effect
        # such as sending an e-mail. Fresh databases also get it here since
        # CREATE TABLE task_runs above predates the column.
        4,
        (_add_action_done_at_column,),
    ),
    (
        # Which embedding model produced a memory's vector. Nullable: NULL
        # marks a legacy row (model unknown), which search only compares
        # when the dimensions match.
        5,
        (_add_embedding_model_column,),
    ),
    (
        # Where a model-written memory came from: 'user' or
        # 'untrusted_context' (written in a turn that had read web pages,
        # emails...). Nullable: NULL marks a legacy row (provenance unknown).
        6,
        (_add_source_column,),
    ),
    (
        # JSON list of the indexes of pre-approved calls a run has executed,
        # so a retry never repeats any of them (action_done_at only covers
        # the primary action). Nullable: NULL = nothing recorded.
        7,
        (_add_executed_calls_column,),
    ),
]


def _table_exists(cursor: sqlite3.Cursor, name: str) -> bool:
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return cursor.fetchone() is not None


def _apply_migrations(cursor: sqlite3.Cursor) -> None:
    current_version = cursor.execute("PRAGMA user_version").fetchone()[0]
    for target_version, statements in MIGRATIONS:
        if current_version >= target_version:
            continue
        print(f"Applying migration to schema version {target_version}...")
        for statement in statements:
            if callable(statement):
                statement(cursor)
            else:
                cursor.execute(statement)
        cursor.execute(f"PRAGMA user_version = {target_version}")
        current_version = target_version


def create_database() -> None:
    if DB_PATH.exists():
        print(f"Database file found: {DB_PATH}")
    else:
        print(f"Database file not found, creating a new one: {DB_PATH}")

    connection = sqlite3.connect(DB_PATH)
    cursor = connection.cursor()

    if not _table_exists(cursor, "people"):
        print("'people' table not found, creating...")
        cursor.execute(
            """
            CREATE TABLE people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                surname TEXT,
                nickname TEXT,
                connection TEXT,
                phone_num TEXT,
                mail TEXT,
                birthday TEXT,
                address TEXT
            )
            """
        )

    if not _table_exists(cursor, "memories"):
        print("'memories' table not found, creating...")
        cursor.execute(
            """
            CREATE TABLE memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id INTEGER,
                layer TEXT NOT NULL CHECK(layer IN ('deep', 'seasonal', 'short')),
                content TEXT NOT NULL,
                embedding BLOB NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                last_accessed TEXT,
                layer_since TEXT,
                layer_hits INTEGER NOT NULL DEFAULT 0,
                metadata TEXT DEFAULT '{}'
            )
            """
        )

    if not _table_exists(cursor, "subagent_runs"):
        print("'subagent_runs' table not found, creating...")
        cursor.execute(
            """
            CREATE TABLE subagent_runs (
                id TEXT PRIMARY KEY,
                task TEXT NOT NULL,
                tier TEXT NOT NULL CHECK(tier IN ('flash', 'pro')),
                status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'failed')),
                summary TEXT,
                report TEXT,
                error TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                finished_at TEXT,
                reported INTEGER NOT NULL DEFAULT 0,
                reported_at TEXT
            )
            """
        )

    if not _table_exists(cursor, "tasks"):
        print("'tasks' table not found, creating...")
        cursor.execute(
            """
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'passive')),
                is_recurring INTEGER NOT NULL DEFAULT 0,
                model TEXT NOT NULL DEFAULT 'flash' CHECK(model IN ('flash', 'pro')),
                cron_expression TEXT,
                scheduled_at TEXT,
                timezone TEXT NOT NULL,
                condition TEXT,
                tool_name TEXT,
                tool_params TEXT,
                pre_approved_calls TEXT,
                max_retries INTEGER NOT NULL DEFAULT 2,
                retry_delay_seconds INTEGER NOT NULL DEFAULT 300,
                timeout_minutes INTEGER NOT NULL DEFAULT 15,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                updated_at TEXT
            )
            """
        )

    if not _table_exists(cursor, "task_runs"):
        print("'task_runs' table not found, creating...")
        cursor.execute(
            """
            CREATE TABLE task_runs (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'failed', 'missed')),
                attempt INTEGER NOT NULL DEFAULT 1,
                summary TEXT,
                report TEXT,
                error TEXT,
                started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                finished_at TEXT,
                reported INTEGER NOT NULL DEFAULT 0,
                reported_at TEXT
            )
            """
        )

    print("Ensuring indexes exist...")
    for statement in INDEXES:
        cursor.execute(statement)

    print("Ensuring memory consolidation schema (layer columns, archive, runs)...")
    memory_schema.apply_schema(connection)

    _apply_migrations(cursor)

    connection.commit()
    connection.close()
    restrict_permissions(DB_PATH)
    print("Database operations completed successfully.")


if __name__ == "__main__":
    create_database()
