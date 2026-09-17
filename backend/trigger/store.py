import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from toolbox import db

VALID_TASK_STATUSES = {"active", "passive"}
VALID_TASK_STATUS_FILTERS = {"all", "active", "passive"}

RECONCILE_ERROR = "The server was restarted while this task run was in progress."
MISSED_ERROR = "The scheduled time passed while the server was not running."

JSON_TASK_FIELDS = ("condition", "tool_params", "pre_approved_calls")
UPDATABLE_TASK_FIELDS = (
    "name",
    "description",
    "status",
    "is_recurring",
    "model",
    "cron_expression",
    "scheduled_at",
    "timezone",
    "condition",
    "tool_name",
    "tool_params",
    "pre_approved_calls",
    "max_retries",
    "retry_delay_seconds",
    "timeout_minutes",
)


def _get_connection() -> sqlite3.Connection:
    return db.connect()


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_load(text: str | None) -> Any:
    if text is None or text == "":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _task_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "status": row["status"],
        "is_recurring": bool(row["is_recurring"]),
        "model": row["model"],
        "cron_expression": row["cron_expression"],
        "scheduled_at": row["scheduled_at"],
        "timezone": row["timezone"],
        "condition": _json_load(row["condition"]),
        "tool_name": row["tool_name"],
        "tool_params": _json_load(row["tool_params"]),
        "pre_approved_calls": _json_load(row["pre_approved_calls"]) or [],
        "max_retries": row["max_retries"],
        "retry_delay_seconds": row["retry_delay_seconds"],
        "timeout_minutes": row["timeout_minutes"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _run_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "status": row["status"],
        "attempt": row["attempt"],
        "summary": row["summary"],
        "report": row["report"],
        "error": row["error"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "reported": bool(row["reported"]),
        "reported_at": row["reported_at"],
    }


def _encode_task_value(field: str, value: Any) -> Any:
    if field in JSON_TASK_FIELDS:
        return json.dumps(value, ensure_ascii=False) if value is not None else None
    if field == "is_recurring":
        return int(bool(value))
    return value


def create_task_row(task: dict[str, Any]) -> None:
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute(
        "INSERT INTO tasks (id, name, description, status, is_recurring, model, "
        "cron_expression, scheduled_at, timezone, condition, tool_name, tool_params, "
        "pre_approved_calls, max_retries, retry_delay_seconds, timeout_minutes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            task["id"],
            task["name"],
            task["description"],
            task["status"],
            int(bool(task["is_recurring"])),
            task["model"],
            task["cron_expression"],
            task["scheduled_at"],
            task["timezone"],
            _encode_task_value("condition", task.get("condition")),
            task["tool_name"],
            _encode_task_value("tool_params", task.get("tool_params")),
            _encode_task_value("pre_approved_calls", task.get("pre_approved_calls")),
            task["max_retries"],
            task["retry_delay_seconds"],
            task["timeout_minutes"],
        ),
    )
    connection.commit()
    connection.close()


def update_task_row(task_id: str, fields: dict[str, Any]) -> bool:
    updatable = {k: v for k, v in fields.items() if k in UPDATABLE_TASK_FIELDS}
    if not updatable:
        return False
    assignments = []
    values: list[Any] = []
    for field, value in updatable.items():
        assignments.append(f"{field} = ?")
        values.append(_encode_task_value(field, value))
    assignments.append("updated_at = ?")
    values.append(_now_utc())
    values.append(task_id)
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute(f"UPDATE tasks SET {', '.join(assignments)} WHERE id = ?", values)
    changed = cursor.rowcount > 0
    connection.commit()
    connection.close()
    return changed


def set_task_status(task_id: str, status: str) -> bool:
    if status not in VALID_TASK_STATUSES:
        raise ValueError(f"invalid task status: {status}")
    return update_task_row(task_id, {"status": status})


def delete_task(task_id: str) -> bool:
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute("DELETE FROM task_runs WHERE task_id = ?", (task_id,))
    cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    changed = cursor.rowcount > 0
    connection.commit()
    connection.close()
    return changed


def get_task(task_id: str) -> dict[str, Any] | None:
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    connection.close()
    return _task_to_dict(row) if row is not None else None


def list_tasks(status: str = "all", limit: int = 100) -> list[dict[str, Any]]:
    if status not in VALID_TASK_STATUS_FILTERS:
        raise ValueError(f"invalid status filter: {status}")
    connection = _get_connection()
    cursor = connection.cursor()
    if status == "all":
        cursor.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)
        )
    else:
        cursor.execute(
            "SELECT * FROM tasks WHERE status = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (status, limit),
        )
    rows = cursor.fetchall()
    connection.close()
    return [_task_to_dict(row) for row in rows]


def create_run(run_id: str, task_id: str) -> None:
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute(
        "INSERT INTO task_runs (id, task_id, status, attempt) "
        "VALUES (?, ?, 'running', 1)",
        (run_id, task_id),
    )
    connection.commit()
    connection.close()


def set_run_attempt(run_id: str, attempt: int) -> None:
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute(
        "UPDATE task_runs SET attempt = ? WHERE id = ? AND status = 'running'",
        (attempt, run_id),
    )
    connection.commit()
    connection.close()


def complete_run(run_id: str, summary: str, report: str) -> None:
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute(
        "UPDATE task_runs SET status = 'completed', summary = ?, report = ?, "
        "finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = ? AND status = 'running'",
        (summary, report, run_id),
    )
    connection.commit()
    connection.close()


def fail_run(
    run_id: str, error: str, summary: str | None = None, report: str | None = None
) -> None:
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute(
        "UPDATE task_runs SET status = 'failed', error = ?, summary = ?, report = ?, "
        "finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = ? AND status = 'running'",
        (error, summary, report, run_id),
    )
    connection.commit()
    connection.close()


def get_run(run_id: str) -> dict[str, Any] | None:
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM task_runs WHERE id = ?", (run_id,))
    row = cursor.fetchone()
    connection.close()
    return _run_to_dict(row) if row is not None else None


def list_runs(task_id: str, limit: int = 10) -> list[dict[str, Any]]:
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute(
        "SELECT * FROM task_runs WHERE task_id = ? "
        "ORDER BY started_at DESC, rowid DESC LIMIT ?",
        (task_id, limit),
    )
    rows = cursor.fetchall()
    connection.close()
    return [_run_to_dict(row) for row in rows]


def count_running() -> int:
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM task_runs WHERE status = 'running'")
    count = cursor.fetchone()[0]
    connection.close()
    return count


def count_runs(task_id: str) -> int:
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM task_runs WHERE task_id = ?", (task_id,))
    count = cursor.fetchone()[0]
    connection.close()
    return count


def mark_run_reported(run_id: str) -> bool:
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute(
        "UPDATE task_runs SET reported = 1, reported_at = ? "
        "WHERE id = ? AND reported = 0",
        (_now_utc(), run_id),
    )
    changed = cursor.rowcount > 0
    connection.commit()
    connection.close()
    return changed


def get_unreported_task_runs() -> list[dict[str, Any]]:
    connection = db.connect_if_exists()
    if connection is None:
        return []
    cursor = connection.cursor()
    cursor.execute(
        "SELECT r.id, r.task_id, t.name AS task_name, r.status, r.error, "
        "r.finished_at FROM task_runs r JOIN tasks t ON t.id = r.task_id "
        "WHERE r.status IN ('completed', 'failed', 'missed') AND r.reported = 0 "
        "ORDER BY r.finished_at"
    )
    rows = cursor.fetchall()
    connection.close()
    return [dict(row) for row in rows]


def reconcile_runs() -> int:
    connection = db.connect_if_exists()
    if connection is None:
        return 0
    cursor = connection.cursor()
    cursor.execute(
        "UPDATE task_runs SET status = 'failed', error = ?, "
        "finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE status = 'running'",
        (RECONCILE_ERROR,),
    )
    changed = cursor.rowcount
    connection.commit()
    connection.close()
    return changed


def finalize_past_one_shot(task_id: str) -> str | None:
    connection = _get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM task_runs WHERE task_id = ?", (task_id,))
    run_count = cursor.fetchone()[0]
    missed_run_id = None
    if run_count == 0:
        missed_run_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO task_runs (id, task_id, status, error, finished_at) "
            "VALUES (?, ?, 'missed', ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))",
            (missed_run_id, task_id, MISSED_ERROR),
        )
    cursor.execute(
        "UPDATE tasks SET status = 'passive', updated_at = ? "
        "WHERE id = ? AND status = 'active'",
        (_now_utc(), task_id),
    )
    connection.commit()
    connection.close()
    return missed_run_id
