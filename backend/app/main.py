import asyncio
import json
import logging
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.errors import GraphRecursionError
from langgraph.types import Command

import i18n
from app.config import get_settings
from app.dashboard import router as dashboard_router
from app.logging_config import configure_file_logging
from app.schemas import ChatRequest, ChatResponse, ToolCallInfo
from app.streaming import StreamRun, encode_frame, get_or_create_run
from graph import (
    CHECKPOINT_DB_PATH,
    build_graph,
    conversations,
    get_lock,
    history,
    purge_expired,
    touch,
)
from graph.state import replace_messages
from memory import scheduler as memory_scheduler
from memory import schema as memory_schema
from subagents.store import cleanup_reported, reconcile_running
from trigger import scheduler as trigger_scheduler
from trigger.store import reconcile_runs as reconcile_trigger_runs

settings = get_settings()

started_at = time.time()

STREAM_HEARTBEAT_SECONDS = 15


async def _reconcile_conversation_registry(checkpointer: Any) -> None:
    """Seed/prune the durable conversation registry from what actually
    exists in rona_checkpoints.db, once at startup.

    Reads through the checkpointer's own aiosqlite connection (no second
    sqlite handle on that file) and never runs `adelete_thread` while
    holding `checkpointer.lock` -- that lock is non-reentrant and
    `adelete_thread` acquires it internally, so nesting would deadlock.
    Registry bookkeeping must never block startup, so any failure here is
    logged and swallowed.
    """
    try:
        async with checkpointer.lock, checkpointer.conn.cursor() as cursor:
            await cursor.execute("SELECT DISTINCT thread_id FROM checkpoints")
            rows = await cursor.fetchall()
        conversations.reconcile(str(row[0]) for row in rows)
    except Exception:
        logging.getLogger("uvicorn.error").exception(i18n.t("main.log_reconcile_failed"))


async def verify_bearer_token(request: Request) -> None:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(
        token.strip(), settings.auth_token
    ):
        raise HTTPException(
            status_code=401,
            detail=i18n.t("main.auth_invalid_token"),
            headers={"WWW-Authenticate": "Bearer"},
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_file_logging(settings)
    memory_schema.ensure_schema()
    reconcile_running()
    reconcile_trigger_runs()
    trigger_scheduler.start()
    async with AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_DB_PATH)) as checkpointer:
        await checkpointer.setup()
        conversations.ensure_schema()
        history.ensure_schema()
        await _reconcile_conversation_registry(checkpointer)
        conversations.sweep_tombstones()
        app.state.graph = build_graph(checkpointer)
        memory_scheduler.start()
        yield
        await memory_scheduler.stop()
        trigger_scheduler.shutdown()


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    dependencies=[Depends(verify_bearer_token)],
)
app.include_router(dashboard_router)

store_lock = asyncio.Lock()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "model": settings.flash_model,
        "uptime_seconds": round(time.time() - started_at, 2),
    }


def _interrupt_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    for interrupt_object in result.get("__interrupt__") or []:
        return interrupt_object.value
    return None


def _tool_call_infos(payload: dict[str, Any]) -> list[ToolCallInfo]:
    infos = []
    for tool_call in payload.get("tool_calls") or []:
        try:
            args = json.loads(tool_call["function"].get("arguments") or "{}")
        except (json.JSONDecodeError, TypeError):
            args = {}
        infos.append(ToolCallInfo(name=tool_call["function"]["name"], args=args))
    return infos


def _final_reply(result: dict[str, Any]) -> str:
    for message in reversed(result.get("messages") or []):
        if message.get("role") == "assistant" and message.get("content"):
            return message["content"]
    return ""


def _repair_dangling_tool_calls(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    repaired = list(messages)
    if (
        repaired
        and repaired[-1].get("role") == "assistant"
        and repaired[-1].get("tool_calls")
    ):
        for tool_call in repaired[-1]["tool_calls"]:
            repaired.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": json.dumps(
                        {
                            "status": "error",
                            "error": "This tool call is a remnant of an incomplete request.",
                        },
                        ensure_ascii=False,
                    ),
                }
            )
    return repaired


async def _run_turn(
    graph: Any,
    conversation_id: str,
    message: str,
    sink: StreamRun | None = None,
) -> dict[str, Any]:
    config = {
        "configurable": {"thread_id": conversation_id},
        "recursion_limit": settings.graph_recursion_limit,
    }
    async with get_lock(conversation_id):
        resume = False
        repaired_messages: list[dict[str, Any]] | None = None
        async with store_lock:
            await purge_expired(settings.conversation_ttl_seconds, graph.checkpointer)
            cleanup_reported(settings.subagent_retention_hours)
            snapshot = await graph.aget_state(config)
            if snapshot.next:
                resume = any(task.interrupts for task in snapshot.tasks)
                if not resume:
                    repaired_messages = _repair_dangling_tool_calls(
                        snapshot.values.get("messages") or []
                    )
            touch(conversation_id)
        if resume:
            graph_input: Any = Command(resume=message)
        elif repaired_messages is not None:
            graph_input = replace_messages(
                [*repaired_messages, {"role": "user", "content": message}]
            )
        else:
            graph_input = {"messages": [{"role": "user", "content": message}]}
        try:
            interrupt_payload: dict[str, Any] | None = None
            final_values: dict[str, Any] = {}
            async for mode, payload in graph.astream(
                graph_input, config, stream_mode=["custom", "updates", "values"]
            ):
                if mode == "custom":
                    if sink is not None:
                        sink.publish("progress", payload)
                elif mode == "updates":
                    candidate = _interrupt_payload(payload)
                    if candidate is not None:
                        interrupt_payload = candidate
                elif mode == "values":
                    final_values = payload
        except GraphRecursionError:
            return {"status": "ok", "reply": i18n.t("main.recursion_limit_reply"), "tool_calls": None}
        if interrupt_payload is not None:
            return {
                "status": "confirmation_required",
                "reply": interrupt_payload.get("question", ""),
                "tool_calls": [
                    info.model_dump() for info in _tool_call_infos(interrupt_payload)
                ],
            }
        return {
            "status": "ok",
            "reply": _final_reply(final_values),
            "tool_calls": None,
        }


@app.post("/chat", response_model=ChatResponse)
async def chat(chat_request: ChatRequest, http_request: Request) -> ChatResponse:
    graph = http_request.app.state.graph
    conversation_id = chat_request.conversation_id or str(uuid.uuid4())
    try:
        result = await _run_turn(graph, conversation_id, chat_request.message)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=i18n.t("main.model_call_failed", exc=exc))
    return ChatResponse(
        reply=result["reply"],
        model=settings.flash_model,
        conversation_id=conversation_id,
        status=result["status"],
        tool_calls=result["tool_calls"],
    )


def _record_turn_history(
    conversation_id: str,
    message: str,
    result: dict[str, Any],
    steps: list[dict[str, Any]],
    started_at_ms: int,
    started_monotonic: float,
) -> None:
    """Persists this turn to graph.history so every client -- not just the
    one that sent the message -- sees it, including a phone app that got
    backgrounded mid-turn and only reconnects after it's already done.
    Recorded even when `status` is "confirmation_required": the old
    client-side saveConversation() saved every turn unconditionally too,
    since the confirmation question is itself the assistant's reply and
    the user's approve/reject continues the same conversation. Never lets
    a storage error break the chat itself -- the SSE "done" event the
    caller publishes right after this still reaches the client either way.

    Both messages are stamped with the turn's start time, the same as the
    old client-side version did -- graph.history._merge_messages orders a
    merged transcript by createdAt, so server- and browser-recorded turns
    must mean the same thing by it.
    """
    total_duration_ms = round((time.monotonic() - started_monotonic) * 1000)
    user_message = {
        "id": str(uuid.uuid4()),
        "role": "user",
        "content": message,
        "createdAt": started_at_ms,
    }
    assistant_message = {
        "id": str(uuid.uuid4()),
        "role": "assistant",
        "content": result["reply"],
        "createdAt": started_at_ms,
        "steps": steps,
        "totalDurationMs": total_duration_ms,
        "awaitingConfirmation": result["status"] == "confirmation_required",
        "toolCalls": result["tool_calls"],
    }
    try:
        history.record_turn(conversation_id, user_message, assistant_message)
    except Exception:
        logging.getLogger("uvicorn.error").exception(
            i18n.t("main.log_history_record_failed")
        )


async def _stream_worker(
    graph: Any, conversation_id: str, message: str, run: StreamRun
) -> None:
    recorder = history.TurnRecorder(run)
    started_at_ms = int(time.time() * 1000)
    started = time.monotonic()
    try:
        try:
            result = await _run_turn(graph, conversation_id, message, sink=recorder)
        except Exception as exc:  # noqa: BLE001
            run.publish(
                "error",
                {
                    "detail": i18n.t("main.model_call_failed", exc=exc),
                    "conversation_id": conversation_id,
                },
            )
        else:
            _record_turn_history(
                conversation_id, message, result, recorder.steps, started_at_ms, started
            )
            run.publish("done", {**result, "conversation_id": conversation_id})
    finally:
        run.finish()


@app.post("/chat/stream")
async def chat_stream(chat_request: ChatRequest, http_request: Request):
    graph = http_request.app.state.graph
    conversation_id = chat_request.conversation_id or str(uuid.uuid4())
    run, created = get_or_create_run(conversation_id)
    if created:
        run.task = asyncio.create_task(
            _stream_worker(graph, conversation_id, chat_request.message, run)
        )
    last_event_id = 0
    header_value = http_request.headers.get("last-event-id")
    if header_value and header_value.isdigit():
        last_event_id = int(header_value)
    backlog, queue = run.subscribe(last_event_id)

    async def event_source():
        yield encode_frame(0, "conversation", {"conversation_id": conversation_id})
        try:
            for event_id, event_type, data in backlog:
                yield encode_frame(event_id, event_type, data)
                if event_type in ("done", "error"):
                    return
            while True:
                try:
                    event_id, event_type, data = await asyncio.wait_for(
                        queue.get(), timeout=STREAM_HEARTBEAT_SECONDS
                    )
                except TimeoutError:
                    yield ": ping\n\n"
                    if run.done and queue.empty():
                        return
                    continue
                yield encode_frame(event_id, event_type, data)
                if event_type in ("done", "error"):
                    return
        finally:
            run.unsubscribe(queue)

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
