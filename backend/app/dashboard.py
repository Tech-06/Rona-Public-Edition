import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import toolbox
from app.config import Settings, get_settings
from app.llm import chat_completion
from app.streaming import drop_run
from graph import CHECKPOINT_DB_PATH, conversations
from graph.threads import get_lock
from subagents import store as subagent_store
from toolbox import envfile
from toolbox import manager as toolbox_manager
from toolbox import packages as toolbox_packages
from toolbox.db import DB_PATH
from toolbox.registry import iter_specs
from toolbox.tools.mem_tool import get_memories
from toolbox.tools.people_tool import get_people
from trigger import scheduler as trigger_scheduler
from trigger import store as trigger_store

settings = get_settings()
router = APIRouter(prefix="/api")

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT_DIR / ".env"

STARTED_AT = time.time()

LOG_TAIL_INTERVAL_SECONDS = 1.0
LOG_TAIL_MAX_SECONDS = 600

_SECRET_FIELDS = {
    "auth_token",
    "flash_model_api",
    "pro_model_api",
    "flash_model_headers",
    "pro_model_headers",
}

_EDITABLE_FIELDS = {
    "log_level",
    "reload",
    "flash_model",
    "flash_model_url",
    "pro_model",
    "pro_model_url",
    "conversation_ttl_seconds",
    "max_history_messages",
    "llm_timeout_seconds",
    "graph_recursion_limit",
    "subagent_max_rounds",
    "subagent_timeout_seconds",
    "subagent_max_concurrent",
    "subagent_retention_hours",
    "subagent_llm_timeout_seconds",
    "subagent_max_context_messages",
    "trigger_timezone",
    "trigger_max_concurrent",
    "trigger_max_rounds",
    "trigger_llm_timeout_seconds",
    "trigger_max_context_messages",
    "web_autostart",
    "web_client_dir",
}


def _file_size(path: Path) -> int | None:
    return path.stat().st_size if path.exists() else None


def _log_path() -> Path:
    path = Path(settings.log_file)
    return path if path.is_absolute() else ROOT_DIR / path


@router.get("/status")
async def get_status():
    return {
        "app": settings.app_name,
        "uptime_seconds": round(time.time() - STARTED_AT, 2),
        "flash_model": settings.flash_model,
        "pro_configured": settings.pro_configured,
        "scheduler_running": trigger_scheduler.is_running(),
        "active_conversations": conversations.count(),
        "running_subagents": subagent_store.count_running(),
        "running_trigger_occurrences": trigger_store.count_running(),
        "db_size_bytes": _file_size(DB_PATH),
        "checkpoint_db_size_bytes": _file_size(CHECKPOINT_DB_PATH),
        "log_size_bytes": _file_size(_log_path()),
    }


def _package_status(manifest) -> dict[str, Any]:
    """Config-completeness summary for one installed custom package.

    Doesn't touch the network -- just checks whether every field the
    package's manifest marks required already has a value (in .env or its
    own config.json/file). Used by both /connections and /packages so
    dashboard.py never has to know about any specific tool.
    """
    config_values = toolbox_packages.load_config_values(manifest)
    missing = [
        field.key
        for field in manifest.config
        if field.required and config_values.get(field.key) in (None, "")
    ]
    return {
        "id": manifest.id,
        "name": manifest.name,
        "version": manifest.version,
        "kind": manifest.kind,
        "description": manifest.description,
        "provides": manifest.provides,
        "requires": manifest.requires,
        "configured": not missing,
        "missing_config": missing,
    }


@router.get("/connections")
async def get_connections():
    packages_status = [_package_status(m) for m in toolbox_packages.load_installed_manifests()]
    return {
        "packages": packages_status,
        "gemini_embedding_configured": bool(os.getenv("GOOGLE_API_KEY"))
        and bool(os.getenv("EMBEDDING_MODEL_NAME")),
        "flash_configured": bool(
            settings.flash_model and settings.flash_model_url and settings.flash_model_api
        ),
        "pro_configured": settings.pro_configured,
        "db_present": DB_PATH.exists(),
        "checkpoint_db_present": CHECKPOINT_DB_PATH.exists(),
    }


@router.post("/connections/probe")
async def probe_connections():
    package_results: dict[str, dict[str, Any]] = {}
    for manifest in toolbox_packages.load_installed_manifests():
        result = await asyncio.to_thread(toolbox_manager.run_health_check, manifest)
        package_results[manifest.id] = {"ok": result.ok, "detail": result.detail}
    llm_ok = True
    llm_detail = "ok"
    try:
        await chat_completion(
            [{"role": "user", "content": "ping"}], timeout=15
        )
    except Exception as exc:  # noqa: BLE001
        llm_ok = False
        llm_detail = str(exc)
    return {
        "packages": package_results,
        "llm": {"ok": llm_ok, "detail": llm_detail},
    }


@router.get("/packages")
async def list_packages():
    manifests = toolbox_packages.load_installed_manifests()
    return {
        "packages": [_package_status(m) for m in manifests],
        "warnings": toolbox.load_warnings(),
    }


@router.get("/tools")
async def list_tools():
    specs = sorted(iter_specs(), key=lambda spec: spec.name)
    return {"tools": [spec.model_dump() for spec in specs]}


@router.get("/config")
async def read_config():
    data = get_settings().model_dump()
    for field in _SECRET_FIELDS:
        data.pop(field, None)
    return {"values": data, "editable": sorted(_EDITABLE_FIELDS)}


def _encode_env_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _validate_candidate(candidate: dict[str, str]) -> str | None:
    kwargs = {
        key.lower(): value
        for key, value in candidate.items()
        if key.lower() in Settings.model_fields
    }
    try:
        Settings(_env_file=None, **kwargs)
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    return None


@router.put("/config")
async def update_config(payload: dict[str, Any]):
    unknown = set(payload) - _EDITABLE_FIELDS
    if unknown:
        raise HTTPException(400, f"Not editable: {', '.join(sorted(unknown))}")
    updates = {field.upper(): _encode_env_value(value) for field, value in payload.items()}
    candidate = {**envfile.read_env_file(ENV_PATH), **updates}
    error = _validate_candidate(candidate)
    if error:
        raise HTTPException(400, error)
    envfile.write_env_updates(ENV_PATH, updates)
    return {"restart_required": True}


@router.get("/tasks")
async def list_tasks(status: str = "all", limit: int = 100):
    try:
        tasks = trigger_store.list_tasks(status, limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    next_runs = trigger_scheduler.next_run_map()
    for task in tasks:
        next_run = next_runs.get(task["id"])
        task["next_run"] = next_run.isoformat() if next_run else None
    return {"tasks": tasks}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    task = trigger_store.get_task(task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    next_run = trigger_scheduler.next_run_map().get(task_id)
    task["next_run"] = next_run.isoformat() if next_run else None
    return task


@router.get("/tasks/{task_id}/runs")
async def list_task_runs(task_id: str, limit: int = 10):
    return {"runs": trigger_store.list_runs(task_id, limit)}


class TaskStatusUpdate(BaseModel):
    status: str


@router.post("/tasks/{task_id}/status")
async def set_task_status(task_id: str, payload: TaskStatusUpdate):
    try:
        changed = trigger_store.set_task_status(task_id, payload.status)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not changed:
        raise HTTPException(404, "Task not found")
    task = trigger_store.get_task(task_id)
    if payload.status == "active":
        trigger_scheduler.register_task(task)
    else:
        trigger_scheduler.unregister_task(task_id)
    return task


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    trigger_scheduler.unregister_task(task_id)
    changed = trigger_store.delete_task(task_id)
    if not changed:
        raise HTTPException(404, "Task not found")
    return {"deleted": True}


@router.get("/subagents")
async def list_subagents(status: str = "all", limit: int = 20):
    try:
        return {"runs": subagent_store.list_runs(status, limit)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/subagents/{run_id}")
async def get_subagent(run_id: str):
    run = subagent_store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


@router.get("/data/notes")
async def data_notes(limit: int = 50, offset: int = 0):
    if not toolbox_manager.is_installed("notes"):
        return {"success": True, "notes": [], "installed": False}
    from toolbox.custom.notes.notes_tool import get_notes

    result = get_notes(limit=limit, offset=offset)
    result["installed"] = True
    return result


@router.get("/data/people")
async def data_people():
    return get_people()


@router.get("/data/memories")
async def data_memories(
    limit: int = 100,
    offset: int = 0,
    person: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
):
    return get_memories(
        limit=limit, offset=offset, person=person, date_from=date_from, date_to=date_to
    )


def _seconds_ago(timestamp: str) -> float:
    try:
        parsed = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return 0.0
    return round(time.time() - parsed.timestamp(), 1)


@router.get("/conversations")
async def list_conversations():
    items = [
        {
            "conversation_id": row["thread_id"],
            "last_active": row["last_active"],
            "last_active_seconds_ago": _seconds_ago(row["last_active"]),
            "pinned": row["pinned"],
        }
        for row in conversations.list_active()
    ]
    return {
        "conversations": items,
        "purged": conversations.list_purged(),
        "ttl_seconds": settings.conversation_ttl_seconds,
        "max_history_messages": settings.max_history_messages,
    }


class ConversationPinUpdate(BaseModel):
    pinned: bool


@router.post("/conversations/{conversation_id}/pin")
async def pin_conversation(conversation_id: str, payload: ConversationPinUpdate):
    return conversations.set_pinned(conversation_id, payload.pinned)


def _get_checkpointer(request: Request):
    graph = getattr(request.app.state, "graph", None)
    checkpointer = getattr(graph, "checkpointer", None)
    if checkpointer is None:
        raise HTTPException(503, "Graph is not ready")
    return checkpointer


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, request: Request):
    checkpointer = _get_checkpointer(request)
    lock = get_lock(conversation_id)
    try:
        await asyncio.wait_for(lock.acquire(), timeout=5.0)
    except asyncio.TimeoutError:
        raise HTTPException(409, "Conversation is busy")
    try:
        delete = getattr(checkpointer, "adelete_thread", None)
        if delete is not None:
            await delete(conversation_id)
        conversations.forget(conversation_id)
    finally:
        lock.release()
    drop_run(conversation_id)
    return {"deleted": True}


@router.delete("/conversations")
async def delete_all_conversations(request: Request):
    checkpointer = _get_checkpointer(request)
    delete = getattr(checkpointer, "adelete_thread", None)
    deleted = 0
    skipped = 0
    for row in conversations.list_active(limit=10_000):
        conversation_id = row["thread_id"]
        lock = get_lock(conversation_id)
        if lock.locked():
            skipped += 1
            continue
        async with lock:
            if delete is not None:
                await delete(conversation_id)
            conversations.forget(conversation_id)
            drop_run(conversation_id)
        deleted += 1
    return {"deleted": deleted, "skipped": skipped}


@router.get("/logs")
async def tail_logs(level: str | None = None, q: str | None = None):
    log_path = _log_path()

    async def event_source():
        offset = log_path.stat().st_size if log_path.exists() else 0
        started = time.monotonic()
        while time.monotonic() - started < LOG_TAIL_MAX_SECONDS:
            await asyncio.sleep(LOG_TAIL_INTERVAL_SECONDS)
            if not log_path.exists():
                continue
            size = log_path.stat().st_size
            if size < offset:
                offset = 0
            if size == offset:
                yield ": ping\n\n"
                continue
            with log_path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                chunk = handle.read(size - offset)
            offset = size
            for line in chunk.splitlines():
                if not line:
                    continue
                if level and f" {level} " not in line:
                    continue
                if q and q.lower() not in line.lower():
                    continue
                yield f"data: {json.dumps(line, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
