import sqlite3

from toolbox.db import DB_PATH

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
)

MIGRATIONS: list[tuple[int, tuple[str, ...]]] = [
    (
        1,
        (
            # Mirrors graph/conversations.py's SCHEMA/INDEX. Duplicated as a
            # literal (rather than imported) so this script stays independent
            # of the app package -- importing `graph` would pull in
            # app.config's Settings(), which requires AUTH_TOKEN/FLASH_MODEL*
            # from .env and would break running this script before .env is
            # filled in. Both copies use IF NOT EXISTS, so any drift between
            # them is harmless: graph.conversations.ensure_schema() also runs
            # at every app startup regardless of whether this migration ran.
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

    _apply_migrations(cursor)

    connection.commit()
    connection.close()
    print("Database operations completed successfully.")


if __name__ == "__main__":
    create_database()
