import asyncio

from graph.nodes import _ARGS_MAX_LENGTH, _filtered_args, _run_tool_call


def test_filtered_args_drops_deny_listed_keys():
    args = {"to": "ali@example.com", "body": "gizli mesaj", "content": "gizli"}
    filtered = _filtered_args(args)
    assert filtered == {"to": "ali@example.com"}


def test_filtered_args_truncates_long_strings():
    args = {"query": "x" * (_ARGS_MAX_LENGTH + 50)}
    filtered = _filtered_args(args)
    assert filtered["query"].endswith("…")
    assert len(filtered["query"]) == _ARGS_MAX_LENGTH + 1


def test_filtered_args_drops_non_scalar_values():
    args = {"n": 5, "ok": True, "ratio": 1.5, "nested": {"a": 1}, "items": [1, 2]}
    filtered = _filtered_args(args)
    assert filtered == {"n": 5, "ok": True, "ratio": 1.5}


def test_run_tool_call_works_without_a_writer():
    tool_call = {
        "id": "call_1",
        "function": {"name": "get_people", "arguments": "{}"},
    }
    message = asyncio.run(_run_tool_call(tool_call, confirmation={}))
    assert message["role"] == "tool"
    assert message["tool_call_id"] == "call_1"


def test_run_tool_call_reports_unknown_tool():
    tool_call = {"id": "call_2", "function": {"name": "does_not_exist", "arguments": "{}"}}
    events = []
    message = asyncio.run(
        _run_tool_call(tool_call, confirmation={}, writer=lambda event: events.append(event))
    )
    assert '"status": "error"' in message["content"]
    assert any(event["type"] == "tool_end" and event["status"] == "unknown_tool" for event in events)


def test_run_tool_call_reports_bad_args():
    tool_call = {"id": "call_3", "function": {"name": "get_people", "arguments": "not json"}}
    events = []
    asyncio.run(_run_tool_call(tool_call, confirmation={}, writer=lambda event: events.append(event)))
    assert any(event["type"] == "tool_end" and event["status"] == "bad_args" for event in events)
