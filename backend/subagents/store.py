import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from toolbox import db

VALID_STATUSES = {"all", "running", "completed", "failed"}

RECONCILE_ERROR = "The server was restarted while this task was running."


def _get_connection() -> sqlite3.Connection:
    return db.connect()


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "task": row["task"],
        "tier": row["tier"],
        "status": row["status"],
        "summary": row["summary"],
        "report": row["report"],
        "error": row["error"],
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
        "reported": bool(row["reported"]),
        "reported_at": row["reported_at"],
    }


def create_run(run_id: str, task: str, tier: str) -> None:
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute(
        "INSERT INTO subagent_runs (id, task, tier, status) VALUES (?, ?, ?, 'running')",
        (run_id, task, tier),
    )
    connection.commit()
    connection.close()


def complete_run(run_id: str, summary: str, report: str) -> None:
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute(
        "UPDATE subagent_runs SET status = 'completed', summary = ?, report = ?, "
        "finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
        (summary, report, run_id),
    )
    connection.commit()
    connection.close()


def fail_run(run_id: str, error: str) -> None:
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute(
        "UPDATE subagent_runs SET status = 'failed', error = ?, "
        "finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
        (error, run_id),
    )
    connection.commit()
    connection.close()


def get_run(run_id: str) -> dict[str, Any] | None:
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM subagent_runs WHERE id = ?", (run_id,))
    row = cursor.fetchone()
    connection.close()
    return _run_to_dict(row) if row is not None else None


def list_runs(status: str = "all", limit: int = 20) -> list[dict[str, Any]]:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status filter: {status}")
    connection = _get_connection()
    cursor = connection.cursor()
    if status == "all":
        cursor.execute(
            "SELECT * FROM subagent_runs ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (limit,),
        )
    else:
        cursor.execute(
            "SELECT * FROM subagent_runs WHERE status = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (status, limit),
        )
    rows = cursor.fetchall()
    connection.close()
    return [_run_to_dict(row) for row in rows]


def count_running() -> int:
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM subagent_runs WHERE status = 'running'")
    count = cursor.fetchone()[0]
    connection.close()
    return count


def mark_reported(run_id: str) -> bool:
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute(
        "UPDATE subagent_runs SET reported = 1, reported_at = ? "
        "WHERE id = ? AND reported = 0",
        (_now_utc(), run_id),
    )
    changed = cursor.rowcount > 0
    connection.commit()
    connection.close()
    return changed


def get_unreported_notifications() -> list[dict[str, Any]]:
    connection = db.connect_if_exists()
    if connection is None:
        return []
    cursor = connection.cursor()
    cursor.execute(
        "SELECT id, task, tier, status, finished_at, error FROM subagent_runs "
        "WHERE status IN ('completed', 'failed') AND reported = 0 "
        "ORDER BY finished_at"
    )
    rows = cursor.fetchall()
    connection.close()
    return [dict(row) for row in rows]


def cleanup_reported(retention_hours: int) -> int:
    if retention_hours <= 0:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=retention_hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    connection = db.connect_if_exists()
    if connection is None:
        return 0
    cursor = connection.cursor()
    cursor.execute(
        "DELETE FROM subagent_runs WHERE reported = 1 AND reported_at <= ?",
        (cutoff,),
    )
    deleted = cursor.rowcount
    connection.commit()
    connection.close()
    return deleted


def reconcile_running() -> int:
    connection = db.connect_if_exists()
    if connection is None:
        return 0
    cursor = connection.cursor()
    cursor.execute(
        "UPDATE subagent_runs SET status = 'failed', error = ?, "
        "finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE status = 'running'",
        (RECONCILE_ERROR,),
    )
    changed = cursor.rowcount
    connection.commit()
    connection.close()
    return changed
