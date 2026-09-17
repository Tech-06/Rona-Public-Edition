import asyncio

import pytest
from langgraph.checkpoint.memory import InMemorySaver

import app.main as main_module
import graph.nodes as nodes_module
from graph import build_graph


class FakeLLM:
    def __init__(self, script):
        self.script = list(script)

    async def __call__(
        self, messages, conversation_id=None, tools=None, tier="flash", timeout=None, stream=False
    ):
        return self.script.pop(0)


class RecordingSink:
    def __init__(self):
        self.events = []

    def publish(self, event_type, data):
        self.events.append((event_type, data))


TOOL_CALL_SCRIPT = [
    {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "get_time", "arguments": "{}"}}
        ],
    },
    {"role": "assistant", "content": "saat geldi"},
]


@pytest.fixture(autouse=True)
def _no_real_db_cleanup(monkeypatch):
    monkeypatch.setattr(main_module, "cleanup_reported", lambda *_args: 0)


async def _run_turn(graph, conversation_id, message, sink=None):
    return await main_module._run_turn(graph, conversation_id, message, sink=sink)


def test_run_turn_plain_reply_shape(monkeypatch):
    monkeypatch.setattr(nodes_module, "chat_completion", FakeLLM([{"role": "assistant", "content": "merhaba"}]))
    graph = build_graph(InMemorySaver())
    result = asyncio.run(_run_turn(graph, "test-parity-plain", "selam"))
    assert result == {"status": "ok", "reply": "merhaba", "tool_calls": None}


def test_run_turn_streaming_matches_non_streaming_result(monkeypatch):
    monkeypatch.setattr(nodes_module, "chat_completion", FakeLLM(list(TOOL_CALL_SCRIPT)))
    plain_graph = build_graph(InMemorySaver())
    plain_result = asyncio.run(_run_turn(plain_graph, "test-parity-plain-2", "saat kaç"))

    monkeypatch.setattr(nodes_module, "chat_completion", FakeLLM(list(TOOL_CALL_SCRIPT)))
    streamed_graph = build_graph(InMemorySaver())
    sink = RecordingSink()
    streamed_result = asyncio.run(
        _run_turn(streamed_graph, "test-parity-streamed", "saat kaç", sink=sink)
    )

    expected = {"status": "ok", "reply": "saat geldi", "tool_calls": None}
    assert plain_result == expected
    assert streamed_result == expected

    progress = [data for event_type, data in sink.events if event_type == "progress"]
    assert any(item["type"] == "tool_start" and item["name"] == "get_time" for item in progress)
    tool_end = next(item for item in progress if item["type"] == "tool_end" and item["name"] == "get_time")
    assert tool_end["status"] == "ok"
    assert isinstance(tool_end["duration_ms"], int)


def test_run_turn_confirmation_required_matches_across_modes(monkeypatch):
    script = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "delete_note", "arguments": '{"note_id": 999999}'},
                }
            ],
        },
        {"role": "assistant", "content": "silmemi onaylıyor musun?"},
    ]
    monkeypatch.setattr(nodes_module, "chat_completion", FakeLLM(list(script)))
    plain_graph = build_graph(InMemorySaver())
    plain_result = asyncio.run(_run_turn(plain_graph, "test-parity-confirm-plain", "notu sil"))

    monkeypatch.setattr(nodes_module, "chat_completion", FakeLLM(list(script)))
    streamed_graph = build_graph(InMemorySaver())
    sink = RecordingSink()
    streamed_result = asyncio.run(
        _run_turn(streamed_graph, "test-parity-confirm-streamed", "notu sil", sink=sink)
    )

    assert plain_result["status"] == streamed_result["status"] == "confirmation_required"
    assert plain_result["reply"] == streamed_result["reply"] == "silmemi onaylıyor musun?"
    assert plain_result["tool_calls"] == streamed_result["tool_calls"] == [
        {"name": "delete_note", "args": {"note_id": 999999}}
    ]
    progress = [data for event_type, data in sink.events if event_type == "progress"]
    assert any(item["type"] == "confirm_start" for item in progress)


def test_run_turn_recursion_limit_uses_the_documented_turkish_reply(monkeypatch):
    monkeypatch.setattr(main_module.settings, "graph_recursion_limit", 3)
    script = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": f"call_{i}",
                    "type": "function",
                    "function": {"name": "get_time", "arguments": "{}"},
                }
            ],
        }
        for i in range(50)
    ]
    monkeypatch.setattr(nodes_module, "chat_completion", FakeLLM(script))
    graph = build_graph(InMemorySaver())
    result = asyncio.run(_run_turn(graph, "test-parity-recursion", "saat kaç"))
    assert result["status"] == "ok"
    assert "tur sınırına ulaştım" in result["reply"]
    assert result["tool_calls"] is None
