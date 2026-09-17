import asyncio
import inspect
import json
import logging
import time
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.llm import chat_completion
from subagents import store
from toolbox.registry import background_tool_names, get_tool, get_tool_schemas, has_tool

settings = get_settings()
logger = logging.getLogger("uvicorn.error")

WORKER_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "prompts" / "subagent_worker.md"
)

WRAP_UP_PROMPT = (
    "You have reached the tool call limit. Do not call any more tools. "
    "Give your final answer now based on what you already have."
)

REPORTER_SYSTEM_PROMPT = (
    "You are the reporting layer of a background task agent. Based on the task "
    "and the agent's final message, produce the final task result. Return only "
    'valid JSON as the response: {"summary": "...", "report": "..."} where '
    "summary is 2 to 4 sentences capturing the key findings and conclusions, "
    "and report is the detailed, self-contained result covering all relevant "
    "details, data and reasoning. Write both in the language the task was given in."
)

_tasks: dict[str, asyncio.Task] = {}


def _load_worker_prompt() -> str:
    if not WORKER_PROMPT_PATH.is_file():
        raise FileNotFoundError(f"Worker prompt file not found: {WORKER_PROMPT_PATH}")
    content = WORKER_PROMPT_PATH.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"Worker prompt file is empty: {WORKER_PROMPT_PATH}")
    return content


def _allowed_tool_names() -> set[str]:
    return background_tool_names()


def _tool_message(call_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(payload, ensure_ascii=False, default=str),
    }


def _trim_worker_messages(
    messages: list[dict[str, Any]], max_messages: int
) -> list[dict[str, Any]]:
    if max_messages <= 0 or len(messages) <= max_messages:
        return messages
    head = messages[:2]
    tail = messages[2:]
    round_starts = [i for i, m in enumerate(tail) if m.get("role") == "assistant"]
    while round_starts and len(head) + len(tail) > max_messages:
        next_boundary = round_starts[1] if len(round_starts) > 1 else len(tail)
        tail = tail[next_boundary:]
        round_starts = [i - next_boundary for i in round_starts[1:]]
    return head + tail


async def _execute_tool_call(
    tool_call: dict[str, Any], allowed_names: set[str]
) -> dict[str, Any]:
    call_id = tool_call["id"]
    name = tool_call["function"]["name"]
    raw_arguments = tool_call["function"].get("arguments") or "{}"
    try:
        args = json.loads(raw_arguments)
    except json.JSONDecodeError:
        args = None
    if args is None:
        return _tool_message(
            call_id, {"status": "error", "error": "Invalid argument JSON"}
        )
    if not has_tool(name) or name not in allowed_names:
        return _tool_message(
            call_id,
            {
                "status": "error",
                "error": f"Tool not available to background tasks: {name}",
            },
        )
    try:
        fn = get_tool(name)
        if inspect.iscoroutinefunction(fn):
            result = await fn(**args)
        else:
            result = await asyncio.to_thread(fn, **args)
    except Exception as exc:  # noqa: BLE001
        return _tool_message(call_id, {"status": "error", "error": str(exc)})
    return _tool_message(call_id, {"status": "ok", "result": result})


async def _agent_loop(
    run_id: str, task: str, tier: str, allowed_names: set[str]
) -> tuple[str, bool]:
    schemas = get_tool_schemas(allowed_names)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _load_worker_prompt()},
        {"role": "user", "content": task},
    ]
    rounds = 0
    while rounds < settings.subagent_max_rounds:
        started = time.monotonic()
        assistant = await chat_completion(
            messages,
            run_id,
            tools=schemas,
            tier=tier,
            timeout=settings.subagent_llm_timeout_seconds,
            stream=True,
        )
        logger.info(
            "[subagent] %s round %d llm %.1fs",
            run_id[:8],
            rounds + 1,
            time.monotonic() - started,
        )
        messages.append(assistant)
        tool_calls = assistant.get("tool_calls") or []
        if not tool_calls:
            return assistant.get("content") or "", False
        tool_messages = await asyncio.gather(
            *(_execute_tool_call(tool_call, allowed_names) for tool_call in tool_calls)
        )
        messages.extend(tool_messages)
        messages = _trim_worker_messages(messages, settings.subagent_max_context_messages)
        rounds += 1
    messages.append({"role": "user", "content": WRAP_UP_PROMPT})
    assistant = await chat_completion(
        messages,
        run_id,
        tier=tier,
        timeout=settings.subagent_llm_timeout_seconds,
        stream=True,
    )
    return assistant.get("content") or "", True


def _parse_report_json(text: str) -> dict[str, str] | None:
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
        return None
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    summary = parsed.get("summary")
    report = parsed.get("report")
    if not isinstance(summary, str) or not summary.strip():
        return None
    if not isinstance(report, str) or not report.strip():
        return None
    return {"summary": summary.strip(), "report": report.strip()}


async def _report(
    run_id: str, task: str, tier: str, final_content: str, capped: bool
) -> dict[str, str]:
    user_content = json.dumps(
        {"task": task, "final_message": final_content, "hit_tool_limit": capped},
        ensure_ascii=False,
    )
    message = await chat_completion(
        [
            {"role": "system", "content": REPORTER_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        run_id,
        tier=tier,
        timeout=settings.subagent_llm_timeout_seconds,
        stream=True,
    )
    parsed = _parse_report_json(message.get("content") or "")
    if parsed is not None:
        return parsed
    fallback_summary = " ".join(final_content.split()[:80])
    return {"summary": fallback_summary, "report": final_content}


async def _execute_run(run_id: str, task: str, tier: str) -> None:
    try:
        async with asyncio.timeout(settings.subagent_timeout_seconds):
            final_content, capped = await _agent_loop(
                run_id, task, tier, _allowed_tool_names()
            )
        if not final_content.strip():
            raise ValueError("The subagent model returned an empty final message.")
        result = await _report(run_id, task, tier, final_content, capped)
        store.complete_run(run_id, result["summary"], result["report"])
        logger.info("[subagent] %s completed (%s)", run_id[:8], tier)
    except asyncio.CancelledError:
        store.fail_run(run_id, "Task was cancelled before completion.")
        raise
    except TimeoutError:
        store.fail_run(
            run_id,
            f"Task timed out after {settings.subagent_timeout_seconds} seconds.",
        )
        logger.warning("[subagent] %s timed out (%s)", run_id[:8], tier)
    except Exception as exc:  # noqa: BLE001
        store.fail_run(run_id, str(exc))
        logger.error("[subagent] %s failed (%s): %s", run_id[:8], tier, exc)
    finally:
        _tasks.pop(run_id, None)


def spawn(run_id: str, task: str, tier: str) -> None:
    _tasks[run_id] = asyncio.create_task(_execute_run(run_id, task, tier))
    logger.info("[subagent] %s started (%s)", run_id[:8], tier)
