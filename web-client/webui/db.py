import sqlite3
from pathlib import Path

from webui.config import get_settings

settings = get_settings()

BACKEND_DIR = (Path(__file__).resolve().parent.parent / settings.backend_dir).resolve()
DB_PATH = BACKEND_DIR / "rona.db"


def _configure(connection: sqlite3.Connection) -> sqlite3.Connection:
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def connect_if_exists() -> sqlite3.Connection | None:
    if not DB_PATH.exists():
        return None
    return _configure(sqlite3.connect(DB_PATH))
