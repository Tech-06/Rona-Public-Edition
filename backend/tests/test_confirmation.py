import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

import app.main as main_module
import graph.nodes as nodes_module
from app import streaming
from app.schemas import ConfirmationDecision
from graph import build_graph
from graph.nodes import INTERPRET_SYSTEM_PROMPT, pending_hash

AUTH = {"Authorization": "Bearer pytest-auth-token-0123456789abcdef"}
SECRET_ARG = "UNIQUE-ARG-VALUE-123"

DELETE_CALL = {
    "id": "call_1",
    "type": "function",
    "function": {
        "name": "delete_person",
        "arguments": json.dumps({"person_id": 999999, "note": SECRET_ARG}),
    },
}


class ScriptedLLM:
    """Plays the agent/question turns; interpreter calls are recorded and
    answered with `interpreter_reply` (or fail the test when forbidden)."""

    def __init__(self, interpreter_reply=None):
        self.script = [
            {"role": "assistant", "content": None, "tool_calls": [DELETE_CALL]},
            {"role": "assistant", "content": "Delete this person?"},
            {"role": "assistant", "content": "all done"},
        ]
        self.interpreter_reply = interpreter_reply
        self.interpreter_prompts = []

    async def __call__(self, messages, conversation_id=None, tools=None, **kwargs):
        if messages and messages[0].get("content") == INTERPRET_SYSTEM_PROMPT:
            if self.interpreter_reply is None:
                pytest.fail("interpreter LLM must not be called for a structured decision")
            self.interpreter_prompts.append(messages)
            return {"role": "assistant", "content": self.interpreter_reply}
        return self.script.pop(0)


@pytest.fixture
def executed(monkeypatch):
    calls = []
    monkeypatch.setattr(nodes_module, "has_tool", lambda name: True)
    monkeypatch.setattr(nodes_module, "requires_confirmation", lambda name, args=None: True)
    monkeypatch.setattr(nodes_module, "get_tool", lambda name: lambda **kw: calls.append(kw) or "ok")
    monkeypatch.setattr(main_module, "cleanup_reported", lambda *_a: 0)
    return calls


def _start(monkeypatch, llm, cid):
    monkeypatch.setattr(nodes_module, "chat_completion", llm)
    graph = build_graph(InMemorySaver())
    first = asyncio.run(main_module._run_turn(graph, cid, "delete him"))
    assert first["status"] == "confirmation_required"
    return graph, first


def _decide(graph, cid, text, **confirmation):
    decision = ConfirmationDecision(**confirmation) if confirmation else None
    return asyncio.run(main_module._run_turn(graph, cid, text, confirmation=decision))


def test_pending_hash_is_exposed_and_stable(monkeypatch, executed):
    graph, first = _start(monkeypatch, ScriptedLLM(), "conf-hash-0001")
    calls = [{"function": DELETE_CALL["function"]}]
    assert first["pending_hash"] == pending_hash(calls)
    assert len(first["pending_hash"]) == 64
    assert pending_hash(calls) == pending_hash([dict(calls[0])])
    other = [{"function": {"name": "delete_person", "arguments": '{"person_id": 1}'}}]
    assert pending_hash(other) != first["pending_hash"]


def test_structured_approval_executes_without_interpreter(monkeypatch, executed):
    graph, first = _start(monkeypatch, ScriptedLLM(), "conf-appr-0001")
    result = _decide(graph, "conf-appr-0001", "yes", approved=True, pending_hash=first["pending_hash"])
    assert result["status"] == "ok"
    assert executed == [{"person_id": 999999, "note": SECRET_ARG}]


def test_structured_rejection_does_not_execute(monkeypatch, executed):
    graph, first = _start(monkeypatch, ScriptedLLM(), "conf-rej-00001")
    result = _decide(graph, "conf-rej-00001", "no", approved=False, pending_hash=first["pending_hash"])
    assert result["status"] == "ok"
    assert executed == []


def test_mismatching_hash_executes_nothing_and_keeps_pending(monkeypatch, executed):
    graph, first = _start(monkeypatch, ScriptedLLM(), "conf-mism-0001")
    with pytest.raises(main_module.ConfirmationMismatch):
        _decide(graph, "conf-mism-0001", "yes", approved=True, pending_hash="0" * 64)
    assert executed == []
    # still awaiting: the correct hash can be used afterwards
    result = _decide(graph, "conf-mism-0001", "yes", approved=True, pending_hash=first["pending_hash"])
    assert result["status"] == "ok"
    assert len(executed) == 1


def test_free_text_interpreter_never_sees_tool_arguments(monkeypatch, executed):
    llm = ScriptedLLM(interpreter_reply='{"approved": true}')
    graph, _ = _start(monkeypatch, llm, "conf-free-0001")
    result = _decide(graph, "conf-free-0001", "yes please")
    assert result["status"] == "ok"
    assert len(executed) == 1
    assert llm.interpreter_prompts
    assert SECRET_ARG not in json.dumps(llm.interpreter_prompts)
    assert "yes please" in json.dumps(llm.interpreter_prompts)


def test_chat_endpoint_mismatch_is_409_and_response_has_hash(monkeypatch, executed):
    streaming._runs.clear()
    monkeypatch.setattr(nodes_module, "chat_completion", ScriptedLLM())
    main_module.app.state.graph = build_graph(InMemorySaver())
    client = TestClient(main_module.app)
    first = client.post(
        "/chat", json={"message": "delete him", "conversation_id": "conf-http-0001"}, headers=AUTH
    )
    body = first.json()
    assert body["status"] == "confirmation_required"
    assert body["pending_hash"] and body["tool_calls"][0]["name"] == "delete_person"

    bad = client.post(
        "/chat",
        json={
            "message": "yes",
            "conversation_id": "conf-http-0001",
            "confirmation": {"approved": True, "pending_hash": "bad"},
        },
        headers=AUTH,
    )
    assert bad.status_code == 409
    assert bad.json()["code"] == "confirmation_mismatch"
    assert executed == []


def test_stream_done_event_carries_pending_hash(monkeypatch, executed):
    streaming._runs.clear()
    monkeypatch.setattr(nodes_module, "chat_completion", ScriptedLLM())
    main_module.app.state.graph = build_graph(InMemorySaver())
    client = TestClient(main_module.app)
    response = client.post(
        "/chat/stream", json={"message": "delete him", "conversation_id": "conf-sse-00001"}, headers=AUTH
    )
    done = response.text.split("event: done\ndata: ")[1].split("\n")[0]
    assert json.loads(done)["pending_hash"]
    streaming._runs.clear()
