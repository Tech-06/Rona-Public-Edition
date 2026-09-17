import asyncio
import inspect
import json
import logging
import time
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter, interrupt

from app.config import get_settings
from app.llm import chat_completion
from app.prompts import load_prompts
from graph.state import RonaState, replace_messages, trim_messages
from subagents.store import get_unreported_notifications
from toolbox import get_tool, get_tool_schemas, has_tool, requires_confirmation
from trigger.store import get_unreported_task_runs

settings = get_settings()
tool_logger = logging.getLogger("uvicorn.error")

NOTIFICATION_SYSTEM_PROMPT = (
    "Background task updates that have not been delivered to the user yet: "
    "{updates} "
    "Briefly mention each of them at the start of your reply, in the user's "
    "language, and offer to share the result of the completed ones."
)

TRIGGER_NOTIFICATION_SYSTEM_PROMPT = (
    "Scheduled task results that have not been delivered to the user yet: "
    "{updates} "
    "Mention every single one of them at the very start of your reply, in the "
    "user's language, BEFORE calling any tools, including for each: the task "
    "name, whether it completed, failed or was missed, and the error reason "
    "for failed and missed ones. This list is the complete, definitive answer "
    "to what happened while the user was away — relaying it never requires "
    "calling list_tasks, get_task or any other tool first, so do not ask for "
    "approval to check. Only after this mention, if the user asks for "
    "something it does not already contain, use get_task_run for details and "
    "dismiss_task_run if the user does not care."
)

QUESTION_SYSTEM_PROMPT = (
    "You are the approval layer for the personal assistant named Rona. "
    "Generate a single, short question to ask the user to approve the tool call "
    "that is about to be executed. The question should be in everyday, natural "
    "language and explicitly include critical parameters (such as recipient, "
    "text, date). Write the question in the language the user used in their "
    "last message. Output only the question text as the response; do not add "
    "any titles, bullet points, or explanations."
)

INTERPRET_SYSTEM_PROMPT = (
    "Evaluate the user's response to a tool call approval request. "
    "If the response contains a clear approval (such as yes, I approve, okay, "
    "send, do it), set approved to true. If it contains a rejection, hesitation, "
    "correction or modification request, off-topic response, or an ambiguous "
    "statement, set approved to false. If you are unsure, choose false. Return "
    'only valid JSON as the response: {"approved": true} or {"approved": false}'
)


_ARGS_DENY_KEYS = {
    "content",
    "body",
    "text",
    "message",
    "report",
    "token",
    "password",
}
_ARGS_MAX_LENGTH = 120


def _filtered_args(args: dict[str, Any]) -> dict[str, Any]:
    filtered: dict[str, Any] = {}
    for key, value in args.items():
        if key in _ARGS_DENY_KEYS:
            continue
        if isinstance(value, str):
            if len(value) > _ARGS_MAX_LENGTH:
                value = value[:_ARGS_MAX_LENGTH] + "…"
            filtered[key] = value
        elif isinstance(value, (int, float, bool)):
            filtered[key] = value
    return filtered


def _round_hint(state: RonaState) -> str:
    messages = state["messages"]
    if messages and messages[-1].get("role") == "tool":
        return "followup"
    return "first"


def _conversation_id(config: RunnableConfig) -> str:
    return config["configurable"]["thread_id"]


def _last_message(state: RonaState) -> dict[str, Any]:
    return state["messages"][-1]


def _last_user_content(state: RonaState) -> str:
    for message in reversed(state["messages"]):
        if message.get("role") == "user":
            return message.get("content") or ""
    return ""


def _confirmable_calls(state: RonaState) -> list[dict[str, Any]]:
    confirmable = []
    for tool_call in _last_message(state).get("tool_calls") or []:
        name = tool_call["function"]["name"]
        if not has_tool(name):
            continue
        try:
            args = json.loads(tool_call["function"].get("arguments") or "{}")
        except json.JSONDecodeError:
            args = None
        if requires_confirmation(name, args):
            confirmable.append(tool_call)
    return confirmable


def _call_summary(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary = []
    for tool_call in tool_calls:
        try:
            args = json.loads(tool_call["function"].get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        summary.append({"name": tool_call["function"]["name"], "args": args})
    return summary


async def agent_node(
    state: RonaState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> dict:
    writer({"type": "agent_start", "hint": _round_hint(state)})
    history = trim_messages(state["messages"], settings.max_history_messages)
    messages = [*load_prompts()]
    try:
        notifications = get_unreported_notifications()
    except Exception:  # noqa: BLE001
        notifications = []
    if notifications:
        messages.append(
            {
                "role": "system",
                "content": NOTIFICATION_SYSTEM_PROMPT.format(
                    updates=json.dumps(notifications, ensure_ascii=False)
                ),
            }
        )
    try:
        trigger_notifications = get_unreported_task_runs()
    except Exception:  # noqa: BLE001
        trigger_notifications = []
    if trigger_notifications:
        messages.append(
            {
                "role": "system",
                "content": TRIGGER_NOTIFICATION_SYSTEM_PROMPT.format(
                    updates=json.dumps(trigger_notifications, ensure_ascii=False)
                ),
            }
        )
    messages.extend(history)
    assistant_message = await chat_completion(
        messages, _conversation_id(config), tools=get_tool_schemas()
    )
    return {
        "messages": replace_messages([*history, assistant_message]),
        "pending_confirmation": None,
        "confirmation": None,
    }


async def ask_confirmation_node(
    state: RonaState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> dict:
    confirmable = _confirmable_calls(state)
    writer(
        {
            "type": "confirm_start",
            "names": [call["function"]["name"] for call in confirmable],
        }
    )
    user_content = json.dumps(
        {
            "user_request": _last_user_content(state),
            "tool_calls": _call_summary(confirmable),
        },
        ensure_ascii=False,
    )
    question_message = await chat_completion(
        [
            {"role": "system", "content": QUESTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        _conversation_id(config),
    )
    question = question_message.get("content") or ""
    updated = {**_last_message(state), "content": question}
    messages = [*state["messages"][:-1], updated]
    return {
        "messages": replace_messages(messages),
        "pending_confirmation": {"question": question, "tool_calls": confirmable},
    }


async def await_confirmation_node(state: RonaState, config: RunnableConfig) -> dict:
    pending = state["pending_confirmation"] or {}
    user_reply = interrupt(pending)
    summary = json.dumps(
        {
            "question": pending.get("question", ""),
            "tool_calls": _call_summary(pending.get("tool_calls") or []),
            "user_reply": user_reply,
        },
        ensure_ascii=False,
    )
    decision_message = await chat_completion(
        [
            {"role": "system", "content": INTERPRET_SYSTEM_PROMPT},
            {"role": "user", "content": summary},
        ],
        _conversation_id(config),
    )
    approved = _parse_approved(decision_message.get("content") or "")
    return {
        "pending_confirmation": None,
        "confirmation": {"approved": approved, "user_reply": user_reply},
    }


def _parse_approved(text: str) -> bool:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        newline = cleaned.find("\n")
        cleaned = cleaned[newline + 1 :] if newline != -1 else ""
        fence_end = cleaned.rfind("```")
        if fence_end != -1:
            cleaned = cleaned[:fence_end]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        return False
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return False
    return parsed.get("approved") is True


async def tools_node(
    state: RonaState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> dict:
    confirmation = state.get("confirmation") or {}
    conversation_id = _conversation_id(config)
    tool_calls = _last_message(state).get("tool_calls") or []
    tool_messages = await asyncio.gather(
        *(
            _run_tool_call(tool_call, confirmation, conversation_id, writer)
            for tool_call in tool_calls
        )
    )
    return {
        "messages": list(tool_messages),
        "pending_confirmation": None,
        "confirmation": None,
    }


async def _run_tool_call(
    tool_call: dict[str, Any],
    confirmation: dict[str, Any],
    conversation_id: str = "",
    writer: StreamWriter = lambda _: None,
) -> dict[str, Any]:
    started = time.monotonic()
    call_id = tool_call["id"]
    name = tool_call["function"]["name"]
    raw_arguments = tool_call["function"].get("arguments") or "{}"
    try:
        args = json.loads(raw_arguments)
    except json.JSONDecodeError:
        args = None
    rejected = (
        args is not None
        and has_tool(name)
        and requires_confirmation(name, args)
        and not confirmation.get("approved")
    )
    args_text = (
        json.dumps(args, ensure_ascii=False, default=str)
        if args is not None
        else raw_arguments
    )
    _log_tool_call(
        conversation_id,
        "approval rejected" if rejected else "tool call",
        name,
        args_text,
    )
    writer(
        {
            "type": "tool_start",
            "call_id": call_id,
            "name": name,
            "args": _filtered_args(args) if isinstance(args, dict) else {},
        }
    )

    def _finish(status: str, payload: dict[str, Any]) -> dict[str, Any]:
        duration_ms = round((time.monotonic() - started) * 1000)
        writer(
            {
                "type": "tool_end",
                "call_id": call_id,
                "name": name,
                "status": status,
                "duration_ms": duration_ms,
            }
        )
        return _tool_message(call_id, payload)

    if args is None:
        return _finish(
            "bad_args", {"status": "error", "error": "Invalid argument JSON"}
        )
    if not has_tool(name):
        return _finish(
            "unknown_tool", {"status": "error", "error": f"Unknown tool: {name}"}
        )
    if rejected:
        return _finish(
            "rejected",
            {
                "status": "rejected",
                "user_reply": confirmation.get("user_reply", ""),
            },
        )
    try:
        fn = get_tool(name)
        if inspect.iscoroutinefunction(fn):
            result = await fn(**args)
        else:
            result = await asyncio.to_thread(fn, **args)
    except Exception as exc:  # noqa: BLE001
        return _finish("error", {"status": "error", "error": str(exc)})
    payload = {"status": "ok", "result": result}
    if confirmation:
        payload["user_reply"] = confirmation.get("user_reply", "")
    return _finish("ok", payload)


def _tool_message(call_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(payload, ensure_ascii=False, default=str),
    }


def _log_tool_call(conversation_id: str, label: str, name: str, args_text: str) -> None:
    tool_logger.info("[%s] %s %s(%s)", label, conversation_id[:8], name, args_text)
