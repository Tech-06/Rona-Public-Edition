import uuid

from app.config import get_settings
from toolbox.registry import has_tool

settings = get_settings()

PRO_NOT_CONFIGURED_ERROR = (
    "PRO model is not configured. "
    "Set PRO_MODEL, PRO_MODEL_URL and PRO_MODEL_API in the server environment."
)

MAX_RETRIES_LIMIT = 20
RETRY_DELAY_LIMIT = 86400
TIMEOUT_LIMIT = 120


def _invalid_int(value, name: str, minimum: int, maximum: int) -> str | None:
    if not isinstance(value, int) or isinstance(value, bool):
        return f"{name} must be an integer."
    if not minimum <= value <= maximum:
        return f"{name} must be between {minimum} and {maximum}."
    return None


def _normalize_pre_approved_calls(calls) -> list[dict] | str:
    if calls is None:
        return []
    if not isinstance(calls, list):
        return "pre_approved_calls must be a list of {tool_name, tool_params} objects."
    normalized = []
    for call in calls:
        if not isinstance(call, dict) or not call.get("tool_name"):
            return "each pre-approved call needs a tool_name."
        name = call["tool_name"]
        if not isinstance(name, str) or not has_tool(name):
            return f"pre-approved call references an unknown tool: {name!r}"
        params = call.get("tool_params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return f"tool_params of pre-approved call {name!r} must be an object."
        normalized.append({"tool_name": name, "tool_params": params})
    return normalized


def _next_run_text(next_run) -> str | None:
    if next_run is None:
        return None
    return next_run.isoformat()


def _task_summary(task: dict, next_run) -> dict:
    return {
        "task_id": task["id"],
        "name": task["name"],
        "description": task["description"],
        "status": task["status"],
        "is_recurring": bool(task["is_recurring"]),
        "model": task["model"],
        "cron_expression": task["cron_expression"],
        "scheduled_at": task["scheduled_at"],
        "timezone": task["timezone"],
        "condition": (task.get("condition") or {}).get("description"),
        "tool_name": task["tool_name"],
        "tool_params": task["tool_params"],
        "pre_approved_calls": task.get("pre_approved_calls") or [],
        "max_retries": task["max_retries"],
        "retry_delay_seconds": task["retry_delay_seconds"],
        "timeout_minutes": task["timeout_minutes"],
        "next_run": _next_run_text(next_run),
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
    }


async def create_task(
    name: str,
    description: str,
    schedule: dict,
    model: str = "flash",
    condition: str = "",
    tool_name: str = "",
    tool_params: dict | None = None,
    pre_approved_calls: list | None = None,
    max_retries: int = 2,
    retry_delay_seconds: int = 300,
    timeout_minutes: int = 15,
) -> dict:
    from trigger import scheduler, store

    try:
        if model not in ("flash", "pro"):
            return {"success": False, "error": "model must be 'flash' or 'pro'."}
        if model == "pro" and not settings.pro_configured:
            return {"success": False, "error": PRO_NOT_CONFIGURED_ERROR}
        if not isinstance(name, str) or not name.strip():
            return {"success": False, "error": "name is required."}
        if not isinstance(description, str) or not description.strip():
            return {"success": False, "error": "description is required."}
        derived = scheduler.derive_schedule(schedule)
        action_name = None
        if isinstance(tool_name, str) and tool_name.strip():
            action_name = tool_name.strip()
            if not has_tool(action_name):
                return {
                    "success": False,
                    "error": f"unknown tool for the task action: {action_name!r}",
                }
            if tool_params is not None and not isinstance(tool_params, dict):
                return {"success": False, "error": "tool_params must be an object."}
        normalized_calls = _normalize_pre_approved_calls(pre_approved_calls)
        if isinstance(normalized_calls, str):
            return {"success": False, "error": normalized_calls}
        for error in (
            _invalid_int(max_retries, "max_retries", 0, MAX_RETRIES_LIMIT),
            _invalid_int(
                retry_delay_seconds, "retry_delay_seconds", 0, RETRY_DELAY_LIMIT
            ),
            _invalid_int(timeout_minutes, "timeout_minutes", 1, TIMEOUT_LIMIT),
        ):
            if error is not None:
                return {"success": False, "error": error}
        task_id = str(uuid.uuid4())
        condition_text = condition.strip() if isinstance(condition, str) else ""
        task_row = {
            "id": task_id,
            "name": name.strip(),
            "description": description.strip(),
            "status": "active",
            "is_recurring": derived["is_recurring"],
            "model": model,
            "cron_expression": derived["cron_expression"],
            "scheduled_at": derived["scheduled_at"],
            "timezone": derived["timezone"],
            "condition": {"description": condition_text} if condition_text else None,
            "tool_name": action_name,
            "tool_params": (tool_params or {}) if action_name else None,
            "pre_approved_calls": normalized_calls,
            "max_retries": max_retries,
            "retry_delay_seconds": retry_delay_seconds,
            "timeout_minutes": timeout_minutes,
        }
        store.create_task_row(task_row)
        next_run = scheduler.register_task(task_row)
        stored = store.get_task(task_id)
        return {
            "success": True,
            "task": _task_summary(stored or task_row, next_run),
            "hint": (
                "The task is now scheduled and will run on the server even if the "
                "user is offline. Tell the user the next run time and the retry "
                "policy. The approval the user just gave covers exactly the "
                "pre-approved calls stored in the task; the executor may not run "
                "them with any other parameters."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


async def list_tasks(status: str = "all") -> dict:
    from trigger import scheduler, store

    try:
        tasks = store.list_tasks(status=status)
        next_runs = scheduler.next_run_map()
        entries = [
            {
                "task_id": task["id"],
                "name": task["name"],
                "status": task["status"],
                "is_recurring": bool(task["is_recurring"]),
                "model": task["model"],
                "cron_expression": task["cron_expression"],
                "scheduled_at": task["scheduled_at"],
                "timezone": task["timezone"],
                "next_run": _next_run_text(next_runs.get(task["id"])),
                "created_at": task["created_at"],
            }
            for task in tasks
        ]
        return {"success": True, "tasks": entries}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def _run_entry(run: dict) -> dict:
    return {
        "run_id": run["id"],
        "task_id": run["task_id"],
        "status": run["status"],
        "attempt": run["attempt"],
        "summary": run["summary"],
        "error": run["error"],
        "started_at": run["started_at"],
        "finished_at": run["finished_at"],
    }


async def get_task(task_id: str, include_runs: bool = True) -> dict:
    from trigger import scheduler, store

    try:
        task = store.get_task(task_id)
        if task is None:
            return {"success": False, "error": f"No task found: {task_id}"}
        next_runs = scheduler.next_run_map()
        payload = {"success": True, "task": _task_summary(task, next_runs.get(task_id))}
        if include_runs:
            payload["runs"] = [_run_entry(run) for run in store.list_runs(task_id)]
        return payload
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


async def update_task(
    task_id: str,
    name: str | None = None,
    description: str | None = None,
    model: str | None = None,
    schedule: dict | None = None,
    condition: str | None = None,
    tool_name: str | None = None,
    tool_params: dict | None = None,
    pre_approved_calls: list | None = None,
    max_retries: int | None = None,
    retry_delay_seconds: int | None = None,
    timeout_minutes: int | None = None,
    status: str | None = None,
) -> dict:
    from trigger import scheduler, store

    try:
        task = store.get_task(task_id)
        if task is None:
            return {"success": False, "error": f"No task found: {task_id}"}
        fields: dict = {}
        if name is not None:
            if not name.strip():
                return {"success": False, "error": "name must not be empty."}
            fields["name"] = name.strip()
        if description is not None:
            if not description.strip():
                return {"success": False, "error": "description must not be empty."}
            fields["description"] = description.strip()
        if model is not None:
            if model not in ("flash", "pro"):
                return {"success": False, "error": "model must be 'flash' or 'pro'."}
            if model == "pro" and not settings.pro_configured:
                return {"success": False, "error": PRO_NOT_CONFIGURED_ERROR}
            fields["model"] = model
        if schedule is not None:
            derived = scheduler.derive_schedule(schedule)
            fields["is_recurring"] = derived["is_recurring"]
            fields["cron_expression"] = derived["cron_expression"]
            fields["scheduled_at"] = derived["scheduled_at"]
            fields["timezone"] = derived["timezone"]
        if condition is not None:
            condition_text = condition.strip() if isinstance(condition, str) else ""
            fields["condition"] = (
                {"description": condition_text} if condition_text else None
            )
        if tool_name is not None:
            if tool_name.strip():
                new_action_name = tool_name.strip()
                if not has_tool(new_action_name):
                    return {
                        "success": False,
                        "error": f"unknown tool for the task action: {tool_name!r}",
                    }
                if tool_params is None:
                    if new_action_name != task["tool_name"]:
                        return {
                            "success": False,
                            "error": (
                                "tool_params is required when changing tool_name to a "
                                "different tool; the previous tool's parameters would "
                                "otherwise carry over and run unreviewed."
                            ),
                        }
                elif not isinstance(tool_params, dict):
                    return {
                        "success": False,
                        "error": "tool_params must be an object.",
                    }
                else:
                    fields["tool_params"] = tool_params
                fields["tool_name"] = new_action_name
            else:
                fields["tool_name"] = None
                fields["tool_params"] = None
        if pre_approved_calls is not None:
            normalized_calls = _normalize_pre_approved_calls(pre_approved_calls)
            if isinstance(normalized_calls, str):
                return {"success": False, "error": normalized_calls}
            fields["pre_approved_calls"] = normalized_calls
        for value, key, maximum in (
            (max_retries, "max_retries", MAX_RETRIES_LIMIT),
            (retry_delay_seconds, "retry_delay_seconds", RETRY_DELAY_LIMIT),
            (timeout_minutes, "timeout_minutes", TIMEOUT_LIMIT),
        ):
            if value is not None:
                minimum = 1 if key == "timeout_minutes" else 0
                error = _invalid_int(value, key, minimum, maximum)
                if error is not None:
                    return {"success": False, "error": error}
                fields[key] = value
        if status is not None:
            if status not in ("active", "passive"):
                return {
                    "success": False,
                    "error": "status must be 'active' or 'passive'.",
                }
            fields["status"] = status
        if not fields:
            return {"success": False, "error": "no updatable fields provided."}
        store.update_task_row(task_id, fields)
        task = store.get_task(task_id)
        if task is None:
            return {"success": False, "error": f"No task found: {task_id}"}
        note = None
        next_run = None
        if task["status"] == "active":
            next_run = scheduler.register_task(task)
            if next_run is None and not task["is_recurring"]:
                task = store.get_task(task_id)
                if task is None:
                    return {"success": False, "error": f"No task found: {task_id}"}
                note = (
                    "The scheduled time is in the past, so the task could not be "
                    "re-activated; it was marked missed and passive. Create a new "
                    "schedule for it if the user still wants it."
                )
        else:
            scheduler.unregister_task(task_id)
        next_runs = scheduler.next_run_map()
        payload = {
            "success": True,
            "task": _task_summary(task, next_runs.get(task_id)),
        }
        if next_run is not None and task["status"] == "active":
            payload["task"]["next_run"] = _next_run_text(next_run)
        if note is not None:
            payload["note"] = note
        return payload
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


async def delete_task(task_id: str) -> dict:
    from trigger import scheduler, store

    try:
        task = store.get_task(task_id)
        if task is None:
            return {"success": False, "error": f"No task found: {task_id}"}
        scheduler.unregister_task(task_id)
        store.delete_task(task_id)
        return {
            "success": True,
            "task_id": task_id,
            "name": task["name"],
            "deleted": True,
            "note": "The task and all of its run history were deleted.",
        }
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


async def get_task_run(run_id: str, detail: bool = False) -> dict:
    from trigger import store

    try:
        run = store.get_run(run_id)
        if run is None:
            return {"success": False, "error": f"No task run found: {run_id}"}
        task = store.get_task(run["task_id"])
        payload = {
            "success": True,
            **_run_entry(run),
            "task_name": task["name"] if task else None,
        }
        if detail and run["report"]:
            payload["report"] = run["report"]
        if run["status"] in ("completed", "failed", "missed"):
            store.mark_run_reported(run_id)
        return payload
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


async def dismiss_task_run(run_id: str) -> dict:
    from trigger import store

    try:
        run = store.get_run(run_id)
        if run is None:
            return {"success": False, "error": f"No task run found: {run_id}"}
        store.mark_run_reported(run_id)
        return {"success": True, "run_id": run_id, "dismissed": True}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}
