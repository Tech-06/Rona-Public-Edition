import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.dashboard as dashboard_module
import create_db
from graph import conversations, history
from toolbox import db as toolbox_db


class _FakeCheckpointer:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def adelete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)


class _FakeGraph:
    def __init__(self) -> None:
        self.checkpointer = _FakeCheckpointer()


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "rona.db"
    sqlite3.connect(str(db_path)).close()
    monkeypatch.setattr(toolbox_db, "DB_PATH", db_path)
    monkeypatch.setattr(create_db, "DB_PATH", db_path)
    create_db.create_database()

    test_app = FastAPI()
    test_app.include_router(dashboard_module.router)
    test_app.state.graph = _FakeGraph()
    return TestClient(test_app), db_path


def _seed_conversation(thread_id: str, content: str = "hello") -> None:
    history.record_turn(
        thread_id,
        {"id": "u1", "role": "user", "content": content, "createdAt": 1},
        {"id": "a1", "role": "assistant", "content": "hi", "createdAt": 1},
    )


# -- GET /history -------------------------------------------------------------


def test_get_history_starts_empty(client):
    api, _ = client
    response = api.get("/api/history")
    assert response.status_code == 200
    assert response.json() == {"conversations": [], "folders": []}


def test_get_history_lists_a_recorded_conversation(client):
    api, _ = client
    _seed_conversation("t1", "hello there")

    response = api.get("/api/history")

    [conv] = response.json()["conversations"]
    assert conv["conversationId"] == "t1"
    assert conv["title"] == "hello there"
    assert conv["pinned"] is False


# -- route ordering: /history/export must not be swallowed by {id} -----------


def test_history_export_route_is_not_shadowed_by_conversation_id(client):
    api, _ = client
    _seed_conversation("t1")

    response = api.get("/api/history/export")

    assert response.status_code == 200
    body = response.json()
    assert "exportedAt" in body
    assert body["conversations"][0]["conversationId"] == "t1"


# -- GET/PATCH /history/{id} ---------------------------------------------------


def test_get_history_conversation_404_for_unknown_id(client):
    api, _ = client
    response = api.get("/api/history/nope")
    assert response.status_code == 404


def test_get_history_conversation_includes_messages(client):
    api, _ = client
    _seed_conversation("t1")

    response = api.get("/api/history/t1")

    assert response.status_code == 200
    assert len(response.json()["messages"]) == 2


def test_patch_history_conversation_renames(client):
    api, _ = client
    _seed_conversation("t1")

    response = api.patch("/api/history/t1", json={"title": "New title"})

    assert response.status_code == 200
    assert response.json()["title"] == "New title"
    assert response.json()["titleCustom"] is True


def test_patch_history_conversation_sets_and_clears_folder(client):
    api, _ = client
    _seed_conversation("t1")
    folder_id = api.post("/api/history/folders", json={"name": "Work"}).json()["id"]

    moved = api.patch("/api/history/t1", json={"folderId": folder_id})
    assert moved.json()["folderId"] == folder_id

    cleared = api.patch("/api/history/t1", json={"folderId": None})
    assert cleared.json()["folderId"] is None


def test_patch_history_conversation_rejects_unknown_fields(client):
    api, _ = client
    _seed_conversation("t1")

    response = api.patch("/api/history/t1", json={"bogus": 1})

    assert response.status_code == 400


def test_patch_history_conversation_404_for_unknown_id(client):
    api, _ = client
    response = api.patch("/api/history/nope", json={"title": "x"})
    assert response.status_code == 404


# -- folders --------------------------------------------------------------------


def test_folder_create_update_delete_roundtrip(client):
    api, _ = client
    created = api.post("/api/history/folders", json={"name": "  Work  "})
    assert created.status_code == 200
    folder_id = created.json()["id"]
    assert created.json()["name"] == "Work"

    updated = api.patch(f"/api/history/folders/{folder_id}", json={"collapsed": True})
    assert updated.json()["collapsed"] is True

    deleted = api.delete(f"/api/history/folders/{folder_id}")
    assert deleted.json() == {"deleted": True}
    assert api.get("/api/history").json()["folders"] == []


def test_update_unknown_folder_404s(client):
    api, _ = client
    response = api.patch("/api/history/folders/nope", json={"name": "x"})
    assert response.status_code == 404


def test_delete_unknown_folder_404s(client):
    api, _ = client
    response = api.delete("/api/history/folders/nope")
    assert response.status_code == 404


# -- import ----------------------------------------------------------------------


def test_import_history_adds_conversations_and_folders(client):
    api, _ = client
    response = api.post(
        "/api/history/import",
        json={
            "conversations": [
                {
                    "conversationId": "migrated",
                    "title": "Migrated chat",
                    "titleCustom": False,
                    "updatedAt": 1000,
                    "pinned": False,
                    "folderId": None,
                    "messages": [],
                }
            ],
            "folders": [{"id": "f1", "name": "Old", "createdAt": 1, "collapsed": False}],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "conversationsImported": 1,
        "conversationsMerged": 0,
        "foldersImported": 1,
    }
    listed = api.get("/api/history").json()
    assert listed["conversations"][0]["conversationId"] == "migrated"
    assert listed["folders"][0]["id"] == "f1"


# -- deleting a conversation also drops its history ------------------------------


def test_delete_conversation_also_deletes_its_history(client):
    api, _ = client
    _seed_conversation("t1")

    response = api.delete("/api/conversations/t1")

    assert response.status_code == 200
    assert history.get("t1") is None


def test_delete_all_conversations_also_clears_history_and_folders(client):
    api, _ = client
    _seed_conversation("t1")
    conversations.touch("t1")
    api.post("/api/history/folders", json={"name": "Work"})

    response = api.delete("/api/conversations")

    assert response.status_code == 200
    assert history.list_index() == []
    assert history.list_folders() == []
