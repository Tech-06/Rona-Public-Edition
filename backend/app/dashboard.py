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

import i18n
import toolbox
from app.config import Settings, get_settings
from app.llm import chat_completion
from app.streaming import drop_run
from graph import CHECKPOINT_DB_PATH, conversations, history
from graph.threads import get_lock
from subagents import store as subagent_store
from toolbox import envfile
from toolbox import manager as toolbox_manager
from toolbox import packages as toolbox_packages
from toolbox.db import DB_PATH
from toolbox.registry import iter_specs
from toolbox.tools.mem_tool import (
    add_memory,
    delete_memory,
    edit_memory,
    get_memories,
    memory_stats,
    search_memories,
)
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
    "language",
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
        # Field metadata only -- no values. Enough to render a form; the
        # values come from the package's own config endpoint, where secrets
        # are stripped.
        "config_fields": [
            toolbox_manager.config_field_payload(field) for field in manifest.config
        ],
        # cli_only actions are left out rather than shown-and-refused: they
        # block far longer than a request may take, or only make sense on the
        # machine the backend itself runs on.
        "actions": [
            toolbox_manager.action_payload(action)
            for action in manifest.actions
            if not action.cli_only
        ],
    }


@router.get("/connections")
async def get_connections():
    packages_status = [_package_status(m) for m in toolbox_packages.load_installed_manifests()]
    return {
        "packages": packages_status,
        "gemini_embedding_configured": bool(os.getenv("GOOGLE_API_KEY"))
        and bool(os.getenv("EMBEDDING_MODEL_NAME")),
        # Same rule as Settings.pro_configured: name + URL is configured, the
        # api key is optional because a gateway may authenticate on a header.
        "flash_configured": bool(settings.flash_model and settings.flash_model_url),
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


def _installed_manifest_or_404(package_id: str):
    try:
        return toolbox_manager.installed_manifest(package_id)
    except toolbox_manager.ManagerError as exc:
        raise HTTPException(404, str(exc)) from exc
    except toolbox_packages.PackageLoadError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/packages/{package_id}/config")
async def read_package_config(package_id: str):
    """Current configuration of one installed package.

    Secrets are never included -- config_field_payload reports only whether
    one is set, the same way /config drops _SECRET_FIELDS.
    """
    manifest = _installed_manifest_or_404(package_id)
    values = toolbox_packages.load_config_values(manifest)
    return {
        "id": manifest.id,
        "fields": [
            toolbox_manager.config_field_payload(field, values) for field in manifest.config
        ],
    }


@router.put("/packages/{package_id}/config")
async def update_package_config(package_id: str, payload: dict[str, Any]):
    manifest = _installed_manifest_or_404(package_id)
    unknown = set(payload) - {field.key for field in manifest.config}
    if unknown:
        raise HTTPException(
            400, i18n.t("dashboard.not_editable", names=", ".join(sorted(unknown)))
        )
    try:
        # Writes .env / config.json and re-runs the health check; blocking, so
        # off the event loop the same way the connection probe goes.
        health = await asyncio.to_thread(
            toolbox_manager.configure_installed, package_id, payload
        )
    except (toolbox_manager.ManagerError, toolbox_packages.PackageLoadError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "ok": True,
        "health": {"ok": health.ok, "detail": health.detail},
        "restart_required": True,
    }


class PackageActionRequest(BaseModel):
    params: dict[str, Any] = {}
    # Handed back verbatim from a previous input_required response. Opaque to
    # everything between the package that produced it and the package that
    # consumes it -- which is what lets a multi-step flow span two requests
    # without the backend holding a session open.
    state: dict[str, Any] | None = None


@router.post("/packages/{package_id}/actions/{action_id}")
async def run_package_action(package_id: str, action_id: str, payload: PackageActionRequest):
    _installed_manifest_or_404(package_id)
    try:
        result = await asyncio.to_thread(
            toolbox_manager.run_action,
            package_id,
            action_id,
            payload.params,
            payload.state,
            allow_cli_only=False,
        )
    except toolbox_manager.ManagerError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "status": result.status,
        "message": result.message,
        "data": result.data,
        "fields": [
            toolbox_manager.config_field_payload(field) for field in result.fields
        ],
        "state": result.state,
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
        raise HTTPException(400, i18n.t("dashboard.not_editable", names=", ".join(sorted(unknown))))
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
        raise HTTPException(404, i18n.t("dashboard.task_not_found"))
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
        raise HTTPException(404, i18n.t("dashboard.task_not_found"))
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
        raise HTTPException(404, i18n.t("dashboard.task_not_found"))
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
        raise HTTPException(404, i18n.t("dashboard.run_not_found"))
    return run


_RUN_KINDS = ("all", "task", "subagent")


@router.get("/runs")
async def list_runs(
    kind: str = "all",
    status: str | None = None,
    reported: bool | None = None,
    limit: int = 50,
):
    """Combined execution history: scheduled-task runs and subagent runs,
    merged and sorted by recency (see ``rona log`` in the CLI).

    Each store validates its own ``status`` values, and they don't fully
    overlap (task runs can be ``missed``, subagent runs can't) -- so
    filtering happens here, generically, after fetching a batch from each
    side that's guaranteed large enough to contain the true top ``limit``
    once merged and re-sorted.
    """
    if kind not in _RUN_KINDS:
        raise HTTPException(400, i18n.t("dashboard.invalid_kind", kind=kind))

    fetch_limit = limit * 2 if kind == "all" else limit
    runs: list[dict[str, Any]] = []
    if kind in ("all", "task"):
        runs.extend({**run, "kind": "task"} for run in trigger_store.list_all_runs(fetch_limit))
    if kind in ("all", "subagent"):
        runs.extend(
            {**run, "kind": "subagent"}
            for run in subagent_store.list_runs("all", fetch_limit)
        )

    if status is not None:
        runs = [run for run in runs if run["status"] == status]
    if reported is not None:
        runs = [run for run in runs if run["reported"] == reported]

    runs.sort(key=lambda run: run.get("started_at") or run.get("created_at") or "", reverse=True)
    return {"runs": runs[:limit]}


@router.get("/runs/{run_id}")
async def get_run_detail(run_id: str):
    run = trigger_store.get_run(run_id)
    if run is not None:
        return {**run, "kind": "task"}
    run = subagent_store.get_run(run_id)
    if run is not None:
        return {**run, "kind": "subagent"}
    raise HTTPException(404, i18n.t("dashboard.run_not_found"))


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str):
    task_run = trigger_store.get_run(run_id)
    if task_run is not None:
        if not task_run["reported"]:
            raise HTTPException(409, i18n.t("dashboard.run_not_reported"))
        trigger_store.delete_run(run_id)
        return {"deleted": True}

    subagent_run = subagent_store.get_run(run_id)
    if subagent_run is not None:
        if not subagent_run["reported"]:
            raise HTTPException(409, i18n.t("dashboard.run_not_reported"))
        subagent_store.delete_run(run_id)
        return {"deleted": True}

    raise HTTPException(404, i18n.t("dashboard.run_not_found"))


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


# The next several endpoints forward `result["error"]` from
# toolbox/tools/mem_tool.py verbatim. Those functions are dual-use --
# also registered as LLM tools -- so their error strings stay English
# everywhere they're used, including here, rather than going through
# i18n.t(): see i18n.py's module docstring.
@router.get("/data/memories/search")
async def search_memories_endpoint(
    q: str,
    person: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 10,
):
    result = search_memories(
        query=q, person=person, date_from=date_from, date_to=date_to, limit=limit
    )
    if not result["success"]:
        raise HTTPException(400, result["error"])
    return result


@router.get("/data/memories/stats")
async def memory_stats_endpoint():
    result = memory_stats()
    if not result["success"]:
        raise HTTPException(400, result["error"])
    return result


class MemoryCreate(BaseModel):
    layer: str
    content: str
    person_id: int | None = None
    metadata: dict[str, Any] | None = None


class MemoryUpdate(BaseModel):
    layer: str | None = None
    content: str | None = None
    person_id: int | None = None
    metadata: dict[str, Any] | None = None


def _memory_error_status(detail: str) -> int:
    return 404 if "not found" in detail.lower() else 400


@router.post("/data/memories")
async def create_memory(payload: MemoryCreate):
    result = add_memory(
        layer=payload.layer,
        content=payload.content,
        person_id=payload.person_id,
        metadata=payload.metadata,
    )
    if not result["success"]:
        raise HTTPException(_memory_error_status(result["error"]), result["error"])
    return result


@router.put("/data/memories/{memory_id}")
async def update_memory(memory_id: int, payload: MemoryUpdate):
    result = edit_memory(
        memory_id=memory_id,
        layer=payload.layer,
        content=payload.content,
        person_id=payload.person_id,
        metadata=payload.metadata,
    )
    if not result["success"]:
        raise HTTPException(_memory_error_status(result["error"]), result["error"])
    return result


@router.delete("/data/memories/{memory_id}")
async def remove_memory(memory_id: int):
    result = delete_memory(memory_id)
    if not result["success"]:
        raise HTTPException(_memory_error_status(result["error"]), result["error"])
    return result


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
        raise HTTPException(503, i18n.t("dashboard.graph_not_ready"))
    return checkpointer


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, request: Request):
    checkpointer = _get_checkpointer(request)
    lock = get_lock(conversation_id)
    try:
        await asyncio.wait_for(lock.acquire(), timeout=5.0)
    except asyncio.TimeoutError:
        raise HTTPException(409, i18n.t("dashboard.conversation_busy"))
    try:
        delete = getattr(checkpointer, "adelete_thread", None)
        if delete is not None:
            await delete(conversation_id)
        conversations.forget(conversation_id)
        history.delete(conversation_id)
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
    busy_ids: set[str] = set()
    for row in conversations.list_active(limit=10_000):
        conversation_id = row["thread_id"]
        lock = get_lock(conversation_id)
        if lock.locked():
            skipped += 1
            busy_ids.add(conversation_id)
            continue
        async with lock:
            if delete is not None:
                await delete(conversation_id)
            conversations.forget(conversation_id)
            drop_run(conversation_id)
        deleted += 1
    # "Delete all" is a full reset, same as the old client-side clearAll()
    # (web-client/frontend/src/lib/storage.ts) that used to wipe folders
    # along with every conversation -- a conversation skipped above (busy,
    # mid-turn) keeps its history row, but its folder_id may now point at a
    # folder that no longer exists; history.get()/list_index() treat that
    # exactly like "no folder", so it's a harmless dangling reference.
    history.delete_all(except_ids=busy_ids)
    history.delete_all_folders()
    return {"deleted": deleted, "skipped": skipped}


def _history_summary_json(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "conversationId": row["thread_id"],
        "title": row["title"],
        "titleCustom": row["title_custom"],
        "updatedAt": row["updated_at"],
        "pinned": row["pinned"],
        "folderId": row["folder_id"],
    }


def _folder_json(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "createdAt": row["created_at"],
        "collapsed": row["collapsed"],
    }


@router.get("/history")
async def get_history():
    """The web client's whole conversation list + folders in one call --
    what storage.ts's loadIndex()/loadFolders() used to read out of
    localStorage, now shared across every device (see graph/history.py)."""
    return {
        "conversations": [_history_summary_json(row) for row in history.list_index()],
        "folders": [_folder_json(row) for row in history.list_folders()],
    }


@router.get("/history/export")
async def export_history():
    """Same shape as the old client-side exportAll() (ConversationExport in
    web-client/frontend/src/lib/storage.ts) so the "export all chats"
    button's download format doesn't change."""
    return history.export_all()


class HistoryImportPayload(BaseModel):
    conversations: list[dict[str, Any]] = []
    folders: list[dict[str, Any]] = []


@router.post("/history/import")
async def import_history(payload: HistoryImportPayload):
    """One-time migration for a browser's pre-server localStorage history
    (see graph.history.import_conversations's docstring). Safe to call more
    than once, from more than one device: a conversation the server already
    has is merged with the incoming copy, never overwritten by it."""
    result = history.import_conversations(payload.conversations, payload.folders)
    return {
        "conversationsImported": result["conversations_imported"],
        "conversationsMerged": result["conversations_merged"],
        "foldersImported": result["folders_imported"],
    }


class FolderCreate(BaseModel):
    name: str


@router.post("/history/folders")
async def create_history_folder(payload: FolderCreate):
    folder = history.create_folder(payload.name)
    if folder is None:
        raise HTTPException(503, i18n.t("dashboard.history_unavailable"))
    return _folder_json(folder)


class FolderUpdate(BaseModel):
    name: str | None = None
    collapsed: bool | None = None


@router.patch("/history/folders/{folder_id}")
async def update_history_folder(folder_id: str, payload: FolderUpdate):
    if payload.name is not None and not history.rename_folder(folder_id, payload.name):
        raise HTTPException(404, i18n.t("dashboard.folder_not_found"))
    if payload.collapsed is not None and not history.set_folder_collapsed(
        folder_id, payload.collapsed
    ):
        raise HTTPException(404, i18n.t("dashboard.folder_not_found"))
    folder = next((f for f in history.list_folders() if f["id"] == folder_id), None)
    if folder is None:
        raise HTTPException(404, i18n.t("dashboard.folder_not_found"))
    return _folder_json(folder)


@router.delete("/history/folders/{folder_id}")
async def delete_history_folder(folder_id: str):
    if not history.delete_folder(folder_id):
        raise HTTPException(404, i18n.t("dashboard.folder_not_found"))
    return {"deleted": True}


@router.get("/history/{conversation_id}")
async def get_history_conversation(conversation_id: str):
    row = history.get(conversation_id)
    if row is None:
        raise HTTPException(404, i18n.t("dashboard.history_not_found"))
    return {**_history_summary_json(row), "messages": row["messages"]}


@router.patch("/history/{conversation_id}")
async def update_history_conversation(conversation_id: str, payload: dict[str, Any]):
    # A raw dict (rather than a strict model with Optional fields) so a
    # caller can distinguish "not provided" from "explicitly clear the
    # folder" (folderId: null) -- an Optional[str] field defaulting to
    # None can't tell those apart. Mirrors app/dashboard.py's own
    # update_config() for the same reason. Keys are camelCase (folderId,
    # not folder_id) to match every other /history response shape, which
    # speaks the frontend's own ConversationSummary/Folder field names
    # directly -- see _history_summary_json().
    unknown = set(payload) - {"title", "folderId"}
    if unknown:
        raise HTTPException(
            400, i18n.t("dashboard.not_editable", names=", ".join(sorted(unknown)))
        )
    if "title" in payload:
        if not history.rename(conversation_id, str(payload["title"] or "")):
            raise HTTPException(404, i18n.t("dashboard.history_not_found"))
    if "folderId" in payload:
        folder_id = payload["folderId"]
        if folder_id is not None and not isinstance(folder_id, str):
            raise HTTPException(400, i18n.t("dashboard.not_editable", names="folderId"))
        if not history.set_folder(conversation_id, folder_id):
            raise HTTPException(404, i18n.t("dashboard.history_not_found"))
    row = history.get(conversation_id)
    if row is None:
        raise HTTPException(404, i18n.t("dashboard.history_not_found"))
    return _history_summary_json(row)


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
