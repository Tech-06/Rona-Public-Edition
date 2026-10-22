import asyncio
from datetime import datetime, timezone

import pytest

from app import prompts
from app.config import Settings
from graph import nodes
from graph.state import trim_messages
from subagents import runner
from trigger import executor

TOKEN = "t" * 32


def _round(i):
    calls = [
        {"id": f"c{i}a", "type": "function", "function": {"name": "x", "arguments": "{}"}},
        {"id": f"c{i}b", "type": "function", "function": {"name": "x", "arguments": "{}"}},
    ]
    return [
        {"role": "assistant", "content": None, "tool_calls": calls},
        {"role": "tool", "tool_call_id": f"c{i}a", "content": "{}"},
        {"role": "tool", "tool_call_id": f"c{i}b", "content": "{}"},
    ]


def test_long_single_turn_keeps_user_message():
    messages = [{"role": "user", "content": "q"}]
    for i in range(20):
        messages += _round(i)
    result = trim_messages(messages, 50)
    assert result[0] == {"role": "user", "content": "q"}
    assert len(result) == len(messages)


def test_multi_turn_cuts_at_turn_boundary():
    messages = []
    for t in range(6):
        messages.append({"role": "user", "content": f"u{t}"})
        messages += _round(t)
        messages.append({"role": "assistant", "content": f"a{t}"})
    result = trim_messages(messages, 12)
    assert result[0]["role"] == "user"
    assert result[0]["content"] == "u4"
    assert result == messages[messages.index(result[0]):]


def test_current_turn_kept_whole_over_limit_with_older_turns_dropped():
    messages = [{"role": "user", "content": "old"}, {"role": "assistant", "content": "r"}]
    messages.append({"role": "user", "content": "new"})
    for i in range(10):
        messages += _round(i)
    result = trim_messages(messages, 10)
    assert result[0]["content"] == "new"


def test_no_user_message_drops_orphans():
    messages = []
    for i in range(10):
        messages += _round(i)
    result = trim_messages(messages, 10)
    assert result and result[0]["role"] == "assistant"
    assert all(m["role"] != "tool" for m in result[:1])
    # every tool result still has its assistant call
    ids = {c["id"] for m in result if m.get("tool_calls") for c in m["tool_calls"]}
    assert {m["tool_call_id"] for m in result if m["role"] == "tool"} <= ids


def test_unchanged_when_within_limit():
    messages = [{"role": "user", "content": "q"}]
    assert trim_messages(messages, 5) is messages
    assert trim_messages(messages, 0) is messages


@pytest.mark.parametrize("module", [executor, runner])
def test_worker_trim_never_starts_tail_with_tool(module):
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
    ]
    for i in range(8):
        messages += _round(i)
    for limit in range(3, 20):
        result = module._trim_worker_messages(messages, limit)
        assert result[:2] == messages[:2]
        tail = result[2:]
        if tail:
            assert tail[0]["role"] == "assistant"
            assert len(tail) >= 3 or tail[0].get("tool_calls") is None


def _settings(monkeypatch, tz):
    s = Settings(_env_file=None, AUTH_TOKEN=TOKEN)
    object.__setattr__(s, "trigger_timezone", tz)
    monkeypatch.setattr(prompts, "get_settings", lambda: s)


def test_datetime_message_fixed_now(monkeypatch):
    _settings(monkeypatch, "Europe/Istanbul")
    now = datetime(2026, 10, 23, 11, 5, tzinfo=timezone.utc)
    assert prompts.current_datetime_message(now) == {
        "role": "system",
        "content": "Current date and time: 2026-10-23 14:05 (Friday), timezone Europe/Istanbul.",
    }


def test_datetime_message_invalid_timezone_falls_back_to_utc(monkeypatch):
    _settings(monkeypatch, "Not/AZone")
    now = datetime(2026, 10, 23, 11, 5, tzinfo=timezone.utc)
    assert prompts.current_datetime_message(now)["content"].endswith("11:05 (Friday), timezone UTC.")


def _count_dt(messages):
    return sum(
        1 for m in messages
        if m["role"] == "system" and m["content"].startswith("Current date and time:")
    )


def test_agent_node_includes_one_datetime_message(monkeypatch):
    seen = []

    async def fake(messages, *a, **k):
        seen.append(list(messages))
        return {"role": "assistant", "content": "hi"}

    monkeypatch.setattr(nodes, "chat_completion", fake)
    monkeypatch.setattr(nodes, "get_unreported_notifications", lambda: [])
    monkeypatch.setattr(nodes, "get_unreported_task_runs", lambda: [])
    state = {"messages": [{"role": "user", "content": "q"}], "pending_confirmation": None, "confirmation": None}
    out = asyncio.run(nodes.agent_node(state, {"configurable": {"thread_id": "t"}}))
    assert _count_dt(seen[0]) == 1
    # not persisted into checkpointed state
    assert _count_dt(out["messages"]["__replace_messages__"]) == 0


def test_subagent_worker_includes_one_datetime_message(monkeypatch):
    seen = []

    async def fake(messages, *a, **k):
        seen.append(list(messages))
        return {"role": "assistant", "content": "done"}

    monkeypatch.setattr(runner, "chat_completion", fake)
    asyncio.run(runner._agent_loop("run1", "task", "flash", set()))
    assert _count_dt(seen[0]) == 1
    assert seen[0][0]["content"] != seen[0][1]["content"]


def test_trigger_worker_includes_one_datetime_message(monkeypatch):
    seen = []

    async def fake(messages, *a, **k):
        seen.append(list(messages))
        return {"role": "assistant", "content": "done"}

    monkeypatch.setattr(executor, "chat_completion", fake)
    task = {"name": "n", "description": "d", "condition": None, "model": "flash", "timeout_minutes": 1}
    try:
        asyncio.run(executor._agent_loop("run1", task, 1, 1, [], None))
    except Exception:  # noqa: BLE001 - only the captured model input matters
        pass
    assert seen and _count_dt(seen[0]) == 1
