"""Error-id responses, log-stream byte handling, history-import validation
and people_tool connection cleanup."""

import re
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.dashboard as dashboard_module
import app.main as main_module
import create_db
from app import streaming
from toolbox import db as toolbox_db
from toolbox.tools import people_tool

AUTH = {"Authorization": "Bearer pytest-auth-token-0123456789abcdef"}
SECRET = "secret-url?key=SHOULD_NOT_LEAK"
ERROR_ID = re.compile(r"\b[0-9a-f]{8}\b")


@pytest.fixture
def dashboard(tmp_path, monkeypatch):
    path = tmp_path / "rona.db"
    monkeypatch.setattr(toolbox_db, "DB_PATH", path)
    monkeypatch.setattr(create_db, "DB_PATH", path)
    create_db.create_database()
    test_app = FastAPI()
    test_app.include_router(dashboard_module.router)
    return TestClient(test_app)


# -- error ids ---------------------------------------------------------------


@pytest.fixture
def chat_client(monkeypatch):
    streaming._runs.clear()
    main_module.app.state.graph = object()

    async def boom(*args, **kwargs):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(main_module, "_run_turn", boom)
    yield TestClient(main_module.app)
    streaming._runs.clear()


def test_chat_502_hides_exception_text_and_carries_an_error_id(chat_client):
    response = chat_client.post(
        "/chat", json={"message": "hi", "conversation_id": "conv-0001"}, headers=AUTH
    )
    assert response.status_code == 502
    assert "SHOULD_NOT_LEAK" not in response.text
    assert ERROR_ID.search(response.json()["detail"])


def test_chat_stream_error_event_hides_exception_text(chat_client):
    response = chat_client.post(
        "/chat/stream", json={"message": "hi", "conversation_id": "conv-0002"}, headers=AUTH
    )
    assert "event: error" in response.text
    assert "SHOULD_NOT_LEAK" not in response.text
    assert ERROR_ID.search(response.text)


def test_consolidation_500_hides_exception_text(dashboard, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(dashboard_module.memory_consolidation, "run_once", boom)
    response = dashboard.post("/api/memory/consolidation/run", json={})
    assert response.status_code == 500
    assert "SHOULD_NOT_LEAK" not in response.text
    assert ERROR_ID.search(response.json()["detail"])


def test_probe_never_returns_the_raw_exception_string(dashboard, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(dashboard_module, "chat_completion", boom)
    response = dashboard.post("/api/connections/probe")
    assert response.status_code == 200
    llm = response.json()["llm"]
    assert llm["ok"] is False
    assert "SHOULD_NOT_LEAK" not in response.text
    assert "RuntimeError" in llm["detail"]
    assert ERROR_ID.search(llm["detail"])


# -- log tailing ---------------------------------------------------------------


def test_log_tailer_emits_each_multibyte_line_exactly_once(tmp_path):
    log = tmp_path / "app.log"
    log.write_bytes("eski satir\n".encode())
    tailer = dashboard_module._LogTailer(log)

    assert tailer.read_lines() is None  # starts at the end

    with log.open("ab") as handle:
        handle.write("ilk: şığöçü İ\n".encode())
        handle.write("ikinci satır ya".encode())  # partial, no newline yet
    assert tailer.read_lines() == ["ilk: şığöçü İ"]

    with log.open("ab") as handle:
        handle.write("rım\nüçüncü\n".encode())
    assert tailer.read_lines() == ["ikinci satır yarım", "üçüncü"]
    assert tailer.read_lines() is None


def test_log_tailer_holds_a_line_split_inside_a_multibyte_char(tmp_path):
    log = tmp_path / "app.log"
    log.write_bytes(b"")
    tailer = dashboard_module._LogTailer(log)
    encoded = "şeker\n".encode()
    log.write_bytes(encoded[:1])  # first byte of a two-byte character
    assert tailer.read_lines() == []
    with log.open("ab") as handle:
        handle.write(encoded[1:])
    assert tailer.read_lines() == ["şeker"]


def test_log_tailer_resets_after_truncation(tmp_path):
    log = tmp_path / "app.log"
    log.write_bytes(b"")
    tailer = dashboard_module._LogTailer(log)
    log.write_bytes("uzun bir satır burada\n".encode())
    assert tailer.read_lines() == ["uzun bir satır burada"]

    log.write_bytes(b"new\n")  # rotated: smaller than the old offset
    assert tailer.read_lines() == ["new"]


# -- history import ------------------------------------------------------------


def _conv(**overrides):
    return {
        "conversationId": "migrated-1",
        "title": "T",
        "titleCustom": False,
        "updatedAt": 1000,
        "pinned": False,
        "folderId": None,
        "messages": [],
        **overrides,
    }


@pytest.mark.parametrize(
    "bad",
    [
        {"updatedAt": "abc"},
        {"updatedAt": -5},
        {"conversationId": "short"},
        {"conversationId": "has spaces here"},
        {"conversationId": "x" * 65},
        {"conversationId": "../../etc/passwd"},
        {"messages": [{}] * 5001},
    ],
)
def test_import_rejects_bad_conversations_with_4xx(dashboard, bad):
    response = dashboard.post("/api/history/import", json={"conversations": [_conv(**bad)]})
    assert response.status_code == 422


def test_import_rejects_bad_folder_timestamp(dashboard):
    response = dashboard.post(
        "/api/history/import",
        json={"folders": [{"id": "f1", "name": "x", "createdAt": "abc"}]},
    )
    assert response.status_code == 422


def test_import_rejects_too_many_conversations(dashboard):
    conversations = [_conv(conversationId=f"conv-{i:05d}") for i in range(1001)]
    response = dashboard.post("/api/history/import", json={"conversations": conversations})
    assert response.status_code == 422


def test_import_unknown_folder_id_means_no_folder(dashboard):
    response = dashboard.post(
        "/api/history/import",
        json={
            "conversations": [_conv(folderId="ghost-folder")],
            "folders": [{"id": "real", "name": "Real", "createdAt": 1, "collapsed": False}],
        },
    )
    assert response.status_code == 200
    listed = dashboard.get("/api/history").json()
    assert listed["conversations"][0]["folderId"] is None


def test_import_known_folder_id_is_kept(dashboard):
    response = dashboard.post(
        "/api/history/import",
        json={
            "conversations": [_conv(folderId="real")],
            "folders": [{"id": "real", "name": "Real", "createdAt": 1, "collapsed": False}],
        },
    )
    assert response.json()["conversationsImported"] == 1
    assert dashboard.get("/api/history").json()["conversations"][0]["folderId"] == "real"


# -- people_tool -----------------------------------------------------------------


class _ClosableConnection:
    def __init__(self):
        self.closed = False

    def cursor(self):
        raise sqlite3.OperationalError("db exploded")

    def close(self):
        self.closed = True


@pytest.mark.parametrize(
    "call",
    [
        lambda: people_tool.add_person("A"),
        lambda: people_tool.edit_person(1, name="B"),
        lambda: people_tool.get_people(),
        lambda: people_tool.search_person("x"),
    ],
)
def test_people_tool_closes_connection_when_the_db_call_raises(monkeypatch, call):
    connection = _ClosableConnection()
    monkeypatch.setattr(people_tool, "_get_connection", lambda: connection)

    result = call()

    assert result["success"] is False
    assert connection.closed is True
