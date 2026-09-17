import json

from graph.state import replace_messages, rona_messages_reducer, trim_messages


def test_reducer_appends_single_dict():
    left = [{"role": "user", "content": "hi"}]
    result = rona_messages_reducer(left, {"role": "assistant", "content": "hello"})
    assert result == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_reducer_appends_list():
    left = [{"role": "user", "content": "hi"}]
    right = [{"role": "tool", "content": "a"}, {"role": "tool", "content": "b"}]
    assert rona_messages_reducer(left, right) == left + right


def test_reducer_replace_envelope_discards_left_entirely():
    left = [{"role": "user", "content": "old"}] * 5
    new_list = [{"role": "user", "content": "fresh"}]
    assert rona_messages_reducer(left, replace_messages(new_list)) == new_list


def test_trim_messages_disabled_when_zero():
    messages = [{"role": "user", "content": str(i)} for i in range(10)]
    assert trim_messages(messages, 0) == messages


def test_trim_messages_noop_under_limit():
    messages = [{"role": "user", "content": str(i)} for i in range(5)]
    assert trim_messages(messages, 10) == messages


def test_trim_messages_cut_point_is_always_a_user_message():
    messages = [
        {"role": "user", "content": "1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "3"},
        {"role": "assistant", "content": "a3"},
    ]
    trimmed = trim_messages(messages, 3)
    assert trimmed == messages[4:]
    assert trimmed[0]["role"] == "user"


def test_worker_trim_preserves_head_and_round_boundaries():
    from subagents.runner import _trim_worker_messages

    messages = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "TASK"},
    ]
    for i in range(10):
        messages.append(
            {"role": "assistant", "tool_calls": [{"id": f"c{i}", "function": {}}]}
        )
        messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": "r"})

    trimmed = _trim_worker_messages(messages, 8)
    assert trimmed[0] == messages[0]
    assert trimmed[1] == messages[1]
    assert len(trimmed) <= 8

    # No orphaned tool message: every tool_call_id in the trimmed list must
    # be introduced by an assistant message earlier in that same list.
    seen_ids: set[str] = set()
    for message in trimmed:
        if message["role"] == "assistant":
            seen_ids.update(tc["id"] for tc in message.get("tool_calls", []))
        elif message["role"] == "tool":
            assert message["tool_call_id"] in seen_ids


def test_worker_trim_noop_under_limit():
    from subagents.runner import _trim_worker_messages

    messages = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "TASK"},
        {"role": "assistant", "tool_calls": [{"id": "c1", "function": {}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "r"},
    ]
    assert _trim_worker_messages(messages, 100) == messages


def test_trigger_worker_trim_matches_subagent_trim_behavior():
    from subagents.runner import _trim_worker_messages as trim_subagent
    from trigger.executor import _trim_worker_messages as trim_trigger

    messages = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": json.dumps({"task": "x"})},
    ]
    for i in range(6):
        messages.append(
            {"role": "assistant", "tool_calls": [{"id": f"c{i}", "function": {}}]}
        )
        messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": "r"})

    assert trim_trigger(list(messages), 6) == trim_subagent(list(messages), 6)
