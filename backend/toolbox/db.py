import os
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "rona.db"


def restrict_permissions(path: Path) -> None:
    """Best-effort chmod 0600 on POSIX (DB and log files hold private data);
    a no-op on Windows, where mode bits don't map to ACLs."""
    if os.name == "nt":
        return
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _configure(connection: sqlite3.Connection) -> sqlite3.Connection:
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Database file not found. Run create_db.py first: {DB_PATH}"
        )
    return _configure(sqlite3.connect(DB_PATH))


def connect_if_exists() -> sqlite3.Connection | None:
    if not DB_PATH.exists():
        return None
    return _configure(sqlite3.connect(DB_PATH))
