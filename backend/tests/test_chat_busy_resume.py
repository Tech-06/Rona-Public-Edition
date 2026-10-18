import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app import streaming

AUTH = {"Authorization": "Bearer pytest-auth-token-0123456789abcdef"}
BUSY_BODY = {
    "detail": main_module.i18n.t("main.conversation_busy"),
    "code": "conversation_busy",
}


@pytest.fixture(autouse=True)
def _clean_runs():
    streaming._runs.clear()
    yield
    streaming._runs.clear()


@pytest.fixture
def client(monkeypatch):
    main_module.app.state.graph = object()
    return TestClient(main_module.app)


def _active_run(conversation_id="conv-001"):
    run, _ = streaming.get_or_create_run(conversation_id)
    return run


def test_stream_without_last_event_id_while_busy_is_409(client):
    _active_run()
    response = client.post(
        "/chat/stream", json={"message": "hi", "conversation_id": "conv-001"}, headers=AUTH
    )
    assert response.status_code == 409
    assert response.json() == BUSY_BODY


def test_chat_while_busy_is_409(client):
    _active_run()
    response = client.post(
        "/chat", json={"message": "hi", "conversation_id": "conv-001"}, headers=AUTH
    )
    assert response.status_code == 409
    assert response.json() == BUSY_BODY


def test_resume_active_run_replays_after_id(client):
    run = _active_run()
    run.publish("progress", {"n": 1})
    run.publish("done", {"status": "ok", "reply": "x"})
    response = client.post(
        "/chat/stream",
        json={"message": "ignored", "conversation_id": "conv-001"},
        headers={**AUTH, "Last-Event-ID": "1"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "id: 2\nevent: done" in response.text
    assert "event: progress" not in response.text


def test_resume_finished_retained_run_does_not_start_new_turn(client, monkeypatch):
    async def boom(*args, **kwargs):
        raise AssertionError("resume must not start a turn")

    monkeypatch.setattr(main_module, "_stream_worker", boom)
    run = _active_run()
    run.publish("done", {"status": "ok", "reply": "x"})
    run.finish()
    response = client.post(
        "/chat/stream",
        json={"message": "m", "conversation_id": "conv-001"},
        headers={**AUTH, "Last-Event-ID": "0"},
    )
    assert response.status_code == 200
    assert "event: done" in response.text


def test_resume_without_run_is_410(client):
    response = client.post(
        "/chat/stream",
        json={"message": "m", "conversation_id": "nope-0001"},
        headers={**AUTH, "Last-Event-ID": "3"},
    )
    assert response.status_code == 410
    assert response.json() == {
        "detail": main_module.i18n.t("main.run_not_found"),
        "code": "run_not_found",
    }


def test_normal_start_unchanged(client, monkeypatch):
    started = []

    async def fake_worker(graph, conversation_id, message, run):
        started.append(message)
        run.publish("done", {"status": "ok", "reply": "hello"})
        run.finish()

    monkeypatch.setattr(main_module, "_stream_worker", fake_worker)
    response = client.post(
        "/chat/stream", json={"message": "hi", "conversation_id": "fresh-001"}, headers=AUTH
    )
    assert response.status_code == 200
    assert started == ["hi"]
    assert "event: done" in response.text


def test_new_message_after_finished_run_starts_a_turn(client, monkeypatch):
    run = _active_run()
    run.finish()
    started = []

    async def fake_worker(graph, conversation_id, message, run):
        started.append(message)
        run.publish("done", {"status": "ok", "reply": "again"})
        run.finish()

    monkeypatch.setattr(main_module, "_stream_worker", fake_worker)
    response = client.post(
        "/chat/stream", json={"message": "second", "conversation_id": "conv-001"}, headers=AUTH
    )
    assert response.status_code == 200
    assert started == ["second"]
