import asyncio
import inspect
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

import i18n
from app.config import get_settings
from app.llm import chat_completion
from toolbox.registry import background_tool_names, get_tool, get_tool_schemas, has_tool
from trigger import store

settings = get_settings()
logger = logging.getLogger("uvicorn.error")

WORKER_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "prompts" / "trigger_worker.md"
)

VALID_OUTCOMES = {"done", "condition_not_met", "failed"}

WRAP_UP_PROMPT = (
    "You have reached the tool call limit. Do not call any more tools. "
    "Give your final verdict JSON now based on what you already have."
)

def _reporter_system_prompt() -> str:
    # A function, not a module constant, so its one localized piece (the
    # worked example's greeting) always reflects the current LANGUAGE --
    # matters for tests that exercise both languages without reloading
    # this module, and costs nothing extra since get_settings() is
    # lru_cache'd.
    greeting = i18n.t("prompt.example_greeting")
    return (
        "You are the reporting layer of a scheduled task executor. Based on the task "
        "and the executor's final message, produce the final task result. Return only "
        'valid JSON as the response: {"summary": "...", "report": "..."} where '
        "summary is 2 to 4 sentences capturing what was done (or what went wrong), "
        "and report is the detailed, self-contained result covering all relevant "
        "details, data and reasoning. Write both in the language the task was given "
        "in. Both fields must contain real, informative content about this specific "
        "task, never placeholder words. Example for a task that had to send a "
        "greeting SMS: "
        '{"summary": "The SMS was sent to Alex at 15:03 with the text '
        f"'{greeting}'. The first attempt hit a transient API error and succeeded on "
        'attempt 2.", "report": "The task fired at 15:00 UTC. The '
        "condition was checked first and held. The pre-approved send_sms call was "
        'executed exactly as approved. The provider confirmed delivery at 15:03."}'
    )

PLACEHOLDER_VALUES = {"summary", "report", "...", "…", "placeholder", "text"}

ACTION_ALREADY_DONE_NOTE = (
    "\n\nNote: the pre-approved action call has already been executed "
    "successfully during this attempt. Do not call it again; finish the "
    "task and produce your verdict."
)

_semaphore: asyncio.Semaphore | None = None
_tasks: dict[str, asyncio.Task] = {}
_active_task_ids: set[str] = set()


def _execution_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.trigger_max_concurrent)
    return _semaphore


def _load_worker_prompt() -> str:
    if not WORKER_PROMPT_PATH.is_file():
        raise FileNotFoundError(f"Worker prompt file not found: {WORKER_PROMPT_PATH}")
    content = WORKER_PROMPT_PATH.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"Worker prompt file is empty: {WORKER_PROMPT_PATH}")
    return content


def _free_tool_names() -> set[str]:
    return background_tool_names()


def _pre_approved_entries(task: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if task.get("tool_name"):
        entries.append(
            {
                "tool_name": task["tool_name"],
                "tool_params": task.get("tool_params") or {},
            }
        )
    for call in task.get("pre_approved_calls") or []:
        if isinstance(call, dict) and call.get("tool_name"):
            entries.append(
                {
                    "tool_name": call["tool_name"],
                    "tool_params": call.get("tool_params") or {},
                }
            )
    return entries


def _match_pre_approved(
    name: str, args: dict[str, Any], entries: list[dict[str, Any]]
) -> dict[str, Any] | None:
    for entry in entries:
        if entry["tool_name"] == name and entry["tool_params"] == args:
            return entry
    return None


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
    tool_call: dict[str, Any],
    free_names: set[str],
    entries: list[dict[str, Any]],
    action_entry: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    call_id = tool_call["id"]
    name = tool_call["function"]["name"]
    raw_arguments = tool_call["function"].get("arguments") or "{}"
    try:
        args = json.loads(raw_arguments)
    except json.JSONDecodeError:
        args = None
    if args is None or not isinstance(args, dict):
        return _tool_message(
            call_id, {"status": "error", "error": "Invalid argument JSON"}
        ), {"is_action": False, "ok": False}
    if not has_tool(name):
        return _tool_message(
            call_id, {"status": "error", "error": f"Unknown tool: {name}"}
        ), {"is_action": False, "ok": False}
    matched = _match_pre_approved(name, args, entries)
    if name not in free_names and matched is None:
        return _tool_message(
            call_id,
            {
                "status": "error",
                "error": (
                    f"Tool not available to scheduled tasks: {name}. Only calls "
                    "exactly matching the pre-approved ones are allowed; do not "
                    "modify the parameters."
                ),
            },
        ), {"is_action": False, "ok": False}
    is_action = action_entry is not None and matched is action_entry
    try:
        fn = get_tool(name)
        if inspect.iscoroutinefunction(fn):
            result = await fn(**args)
        else:
            result = await asyncio.to_thread(fn, **args)
    except Exception as exc:  # noqa: BLE001
        return _tool_message(call_id, {"status": "error", "error": str(exc)}), {
            "is_action": is_action,
            "ok": False,
        }
    return _tool_message(call_id, {"status": "ok", "result": result}), {
        "is_action": is_action,
        "ok": True,
    }


def _extract_json_object(text: str) -> dict[str, Any] | None:
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
    return parsed if isinstance(parsed, dict) else None


def _parse_verdict(text: str) -> dict[str, Any] | None:
    parsed = _extract_json_object(text)
    if parsed is None:
        return None
    outcome = parsed.get("outcome")
    message = parsed.get("message")
    if (
        outcome not in VALID_OUTCOMES
        or not isinstance(message, str)
        or not message.strip()
    ):
        return None
    return {"outcome": outcome, "message": message.strip()}


def _parse_report_json(text: str) -> dict[str, str] | None:
    parsed = _extract_json_object(text)
    if parsed is None:
        return None
    summary = parsed.get("summary")
    report = parsed.get("report")
    if not isinstance(summary, str) or not summary.strip():
        return None
    if not isinstance(report, str) or not report.strip():
        return None
    if summary.strip().lower() in PLACEHOLDER_VALUES:
        return None
    if report.strip().lower() in PLACEHOLDER_VALUES:
        return None
    if len(summary.strip()) < 12 or len(report.strip()) < 12:
        return None
    return {"summary": summary.strip(), "report": report.strip()}


def _worker_payload(
    task: dict[str, Any],
    attempt: int,
    max_attempts: int,
    entries: list[dict[str, Any]],
) -> str:
    condition = task.get("condition") or {}
    return json.dumps(
        {
            "task_name": task["name"],
            "description": task["description"],
            "condition": condition.get("description"),
            "pre_approved_calls": [
                {"tool_name": entry["tool_name"], "tool_params": entry["tool_params"]}
                for entry in entries
            ],
            "attempt": attempt,
            "max_attempts": max_attempts,
        },
        ensure_ascii=False,
    )


async def _agent_loop(
    run_id: str,
    task: dict[str, Any],
    attempt: int,
    max_attempts: int,
    entries: list[dict[str, Any]],
    action_entry: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str, bool, str | None, bool]:
    free_names = _free_tool_names()
    allowed_names = free_names | {entry["tool_name"] for entry in entries}
    schemas = get_tool_schemas(allowed_names)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _load_worker_prompt()},
        {
            "role": "user",
            "content": _worker_payload(task, attempt, max_attempts, entries),
        },
    ]
    action_ok = False
    rounds = 0
    try:
        async with asyncio.timeout(task["timeout_minutes"] * 60):
            while rounds < settings.trigger_max_rounds:
                started = time.monotonic()
                assistant = await chat_completion(
                    messages,
                    run_id,
                    tools=schemas,
                    tier=task["model"],
                    timeout=settings.trigger_llm_timeout_seconds,
                    stream=True,
                )
                logger.info(
                    i18n.t("trigger.log_round"),
                    run_id[:8],
                    attempt,
                    rounds + 1,
                    time.monotonic() - started,
                )
                messages.append(assistant)
                tool_calls = assistant.get("tool_calls") or []
                if not tool_calls:
                    content = assistant.get("content") or ""
                    return _parse_verdict(content), content, action_ok, None, False
                results = await asyncio.gather(
                    *(
                        _execute_tool_call(tool_call, free_names, entries, action_entry)
                        for tool_call in tool_calls
                    )
                )
                for message, meta in results:
                    messages.append(message)
                    if meta["is_action"] and meta["ok"]:
                        if not action_ok:
                            messages[0] = {
                                **messages[0],
                                "content": messages[0]["content"]
                                + ACTION_ALREADY_DONE_NOTE,
                            }
                        action_ok = True
                messages = _trim_worker_messages(
                    messages, settings.trigger_max_context_messages
                )
                rounds += 1
            messages.append({"role": "user", "content": WRAP_UP_PROMPT})
            assistant = await chat_completion(
                messages,
                run_id,
                tier=task["model"],
                timeout=settings.trigger_llm_timeout_seconds,
                stream=True,
            )
            content = assistant.get("content") or ""
            return _parse_verdict(content), content, action_ok, None, True
    except TimeoutError:
        return (
            None,
            "",
            action_ok,
            i18n.t("trigger.outcome_timeout", minutes=task["timeout_minutes"]),
            False,
        )
    except Exception as exc:  # noqa: BLE001
        return None, "", action_ok, str(exc), False


async def _report(
    run_id: str,
    task: dict[str, Any],
    final_message: str,
    capped: bool,
    abnormal_end: str | None = None,
) -> dict[str, str]:
    user_content = json.dumps(
        {
            "task_name": task["name"],
            "description": task["description"],
            "final_message": final_message,
            "hit_tool_limit": capped,
            "abnormal_end": abnormal_end,
        },
        ensure_ascii=False,
    )
    try:
        message = await chat_completion(
            [
                {"role": "system", "content": _reporter_system_prompt()},
                {"role": "user", "content": user_content},
            ],
            run_id,
            tier=task["model"],
            timeout=settings.trigger_llm_timeout_seconds,
            stream=True,
        )
        parsed = _parse_report_json(message.get("content") or "")
        if parsed is not None:
            logger.info(
                i18n.t("trigger.log_report_ok"),
                run_id[:8],
                len(parsed["summary"]),
            )
            return parsed
        logger.warning(
            i18n.t("trigger.log_report_fallback"),
            run_id[:8],
            (message.get("content") or "")[:200],
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(i18n.t("trigger.log_reporter_failed"), run_id[:8], exc)
    fallback_summary = " ".join(final_message.split()[:80])
    return {"summary": fallback_summary, "report": final_message}


async def _run_attempt(
    run_id: str,
    task: dict[str, Any],
    attempt: int,
    max_attempts: int,
    entries: list[dict[str, Any]],
    action_entry: dict[str, Any] | None,
) -> dict[str, Any]:
    verdict, raw_content, action_ok, loop_error, capped = await _agent_loop(
        run_id, task, attempt, max_attempts, entries, action_entry
    )
    if verdict is not None:
        message = verdict["message"]
        if verdict["outcome"] == "done":
            report_result = await _report(run_id, task, message, capped)
            return {
                "kind": "done",
                "summary": report_result["summary"],
                "report": report_result["report"],
            }
        if verdict["outcome"] == "condition_not_met":
            return {
                "kind": "retry",
                "error": i18n.t("trigger.outcome_condition_not_met"),
                "message": message,
            }
        return {
            "kind": "retry",
            "error": message or i18n.t("trigger.outcome_reported_failure"),
            "message": message,
        }
    if action_ok:
        fallback_message = raw_content.strip() or (
            i18n.t("trigger.outcome_abnormal_end", loop_error=loop_error)
        )
        report_result = await _report(
            run_id, task, fallback_message, capped, abnormal_end=loop_error
        )
        return {
            "kind": "done",
            "summary": report_result["summary"],
            "report": report_result["report"],
        }
    error = loop_error or i18n.t("trigger.outcome_empty_message")
    return {"kind": "retry", "error": error, "message": raw_content}


async def _execute_occurrence(run_id: str, task_id: str) -> None:
    try:
        task = store.get_task(task_id)
        if task is None or task["status"] != "active":
            store.fail_run(run_id, i18n.t("trigger.outcome_not_active"))
            return
        max_attempts = max(1, task["max_retries"] + 1)
        last: dict[str, Any] | None = None
        for attempt in range(1, max_attempts + 1):
            current = store.get_task(task_id)
            if current is None:
                return
            if current["status"] != "active":
                store.fail_run(run_id, i18n.t("trigger.outcome_deactivated"))
                return
            task = current
            if attempt > 1:
                store.set_run_attempt(run_id, attempt)
            entries = _pre_approved_entries(task)
            action_entry = entries[0] if task.get("tool_name") else None
            async with _execution_semaphore():
                result = await _run_attempt(
                    run_id, task, attempt, max_attempts, entries, action_entry
                )
            if result["kind"] == "done":
                store.complete_run(run_id, result["summary"], result["report"])
                if not task["is_recurring"]:
                    store.set_task_status(task_id, "passive")
                logger.info(i18n.t("trigger.log_completed"), run_id[:8], attempt)
                return
            last = result
            logger.warning(
                i18n.t("trigger.log_attempt_failed"),
                run_id[:8],
                attempt,
                result["error"],
            )
            if attempt < max_attempts:
                await asyncio.sleep(task["retry_delay_seconds"])
        if last is not None:
            summary = " ".join((last.get("message") or "").split()[:80])
            store.fail_run(
                run_id, last["error"], summary=summary, report=last.get("message")
            )
            if not task["is_recurring"]:
                store.set_task_status(task_id, "passive")
            logger.error(i18n.t("trigger.log_failed_after_attempts"), run_id[:8], max_attempts)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        try:
            store.fail_run(run_id, str(exc))
        except Exception as store_exc:  # noqa: BLE001
            logger.error(i18n.t("trigger.log_persist_failure_failed"), run_id[:8], store_exc)
        logger.error(i18n.t("trigger.log_failed"), run_id[:8], exc)
    finally:
        _tasks.pop(run_id, None)
        _active_task_ids.discard(task_id)


async def fire(task_id: str) -> None:
    try:
        task = store.get_task(task_id)
        if task is None or task["status"] != "active":
            logger.info(i18n.t("trigger.log_fire_skipped_inactive"), task_id[:8])
            return
        if task_id in _active_task_ids:
            logger.warning(i18n.t("trigger.log_fire_skipped_running"), task_id[:8])
            return
        run_id = str(uuid.uuid4())
        store.create_run(run_id, task_id)
        _active_task_ids.add(task_id)
        _tasks[run_id] = asyncio.create_task(_execute_occurrence(run_id, task_id))
        logger.info(i18n.t("trigger.log_fired"), run_id[:8], task["name"])
    except Exception as exc:  # noqa: BLE001
        logger.error(i18n.t("trigger.log_fire_failed"), task_id[:8], exc)
