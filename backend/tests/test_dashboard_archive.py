"""Tests for the dashboard's archive/consolidation/person-deletion API
surface: manual archive/restore/delete of a memory, person deletion
archiving exactly that person's memories, notes deletion, and the
consolidation status/run endpoints.

Follows the same tmp_path + monkeypatch(toolbox.db.DB_PATH) fixture
pattern as tests/test_dashboard_memory.py -- the real backend/rona.db is
never touched, and the server/scheduler are never started.
"""

import sqlite3
import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.dashboard as dashboard_module
import create_db
from memory import archive as memory_archive
from memory import consolidation as memory_consolidation
from memory import policy as memory_policy
from memory import schema as memory_schema
from toolbox import db as toolbox_db
from toolbox.tools import mem_tool as mem_tool_module
from toolbox.tools import people_tool as people_tool_module


def _fake_embedding(text: str, task_type: str) -> list[float]:
    """Deterministic stand-in for the real Gemini embedding call, same as
    tests/test_dashboard_memory.py."""
    return [float(len(text) % 7 + 1), float(len(text) % 5 + 1), 1.0]


@pytest.fixture(autouse=True)
def _clean_heal_cache():
    memory_schema._reset_heal_cache()
    yield
    memory_schema._reset_heal_cache()


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "rona.db"
    sqlite3.connect(str(db_path)).close()
    monkeypatch.setattr(toolbox_db, "DB_PATH", db_path)
    monkeypatch.setattr(create_db, "DB_PATH", db_path)
    create_db.create_database()
    monkeypatch.setattr(mem_tool_module, "_get_embedding", _fake_embedding)
    # No real .env is needed for any of these tests -- a fixed policy keeps
    # consolidation/access-recording code paths from reading real settings.
    fixed_policy = memory_policy.MemoryPolicy()
    monkeypatch.setattr(memory_policy, "current_policy", lambda: fixed_policy)

    test_app = FastAPI()
    test_app.include_router(dashboard_module.router)
    return TestClient(test_app), db_path


def _add_person(db_path, name: str = "Ada") -> int:
    connection = sqlite3.connect(str(db_path))
    cursor = connection.execute("INSERT INTO people (name) VALUES (?)", (name,))
    connection.commit()
    person_id = cursor.lastrowid
    connection.close()
    return person_id


# ---- GET /data/memories: detailed fields + layer filter -------------------------


def test_list_memories_detailed_fields_and_total(client):
    test_client, _ = client
    test_client.post("/api/data/memories", json={"layer": "short", "content": "loves tea"})

    response = test_client.get("/api/data/memories", params={"person": "all"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["total"] == 1
    memory = data["memories"][0]
    for field in (
        "id",
        "person_id",
        "layer",
        "content",
        "created_at",
        "metadata",
        "access_count",
        "layer_hits",
        "layer_since",
        "last_accessed",
    ):
        assert field in memory
    assert memory["access_count"] == 0
    assert memory["layer_hits"] == 0


def test_list_memories_layer_filter(client):
    test_client, _ = client
    test_client.post("/api/data/memories", json={"layer": "short", "content": "short one"})
    test_client.post("/api/data/memories", json={"layer": "deep", "content": "deep one"})

    response = test_client.get("/api/data/memories", params={"person": "all", "layer": "short"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["memories"][0]["layer"] == "short"


def test_list_memories_invalid_layer_returns_400(client):
    test_client, _ = client
    response = test_client.get("/api/data/memories", params={"person": "all", "layer": "bogus"})
    assert response.status_code == 400


# ---- archive -> list -> restore -> archive -> delete chain -----------------------


def test_archive_restore_delete_chain(client):
    test_client, _ = client
    created = test_client.post(
        "/api/data/memories", json={"layer": "deep", "content": "remember this"}
    ).json()
    memory_id = created["id"]

    archive_resp = test_client.post(f"/api/data/memories/{memory_id}/archive")
    assert archive_resp.status_code == 200
    archive_id = archive_resp.json()["archive_id"]

    listing = test_client.get("/api/data/memories", params={"person": "all"}).json()
    assert listing["memories"] == []

    archived_listing = test_client.get("/api/data/archive").json()
    assert archived_listing["success"] is True
    assert archived_listing["total"] == 1
    archived_row = archived_listing["archive"][0]
    assert archived_row["id"] == archive_id
    assert archived_row["memory_id"] == memory_id
    assert archived_row["reason"] == "manual"
    assert archived_row["layer"] == "deep"
    assert "embedding" not in archived_row

    restore_resp = test_client.post(f"/api/data/archive/{archive_id}/restore")
    assert restore_resp.status_code == 200
    assert restore_resp.json()["memory_id"] == memory_id

    listing_after_restore = test_client.get("/api/data/memories", params={"person": "all"}).json()
    assert len(listing_after_restore["memories"]) == 1
    restored = listing_after_restore["memories"][0]
    assert restored["id"] == memory_id
    assert restored["layer"] == "deep"

    assert test_client.get("/api/data/archive").json()["total"] == 0

    archive_resp_2 = test_client.post(f"/api/data/memories/{memory_id}/archive")
    archive_id_2 = archive_resp_2.json()["archive_id"]

    delete_resp = test_client.delete(f"/api/data/archive/{archive_id_2}")
    assert delete_resp.status_code == 200
    assert test_client.get("/api/data/archive").json()["total"] == 0


def test_archive_missing_memory_returns_404(client):
    test_client, _ = client
    response = test_client.post("/api/data/memories/999/archive")
    assert response.status_code == 404


def test_restore_missing_archive_returns_404(client):
    test_client, _ = client
    response = test_client.post("/api/data/archive/999/restore")
    assert response.status_code == 404


def test_delete_archive_missing_returns_404(client):
    test_client, _ = client
    response = test_client.delete("/api/data/archive/999")
    assert response.status_code == 404


# ---- person deletion --------------------------------------------------------------


def test_delete_person_archives_only_that_persons_memories(client):
    test_client, db_path = client
    ada_id = _add_person(db_path, "Ada")
    bob_id = _add_person(db_path, "Bob")

    ada_memory = test_client.post(
        "/api/data/memories",
        json={"layer": "deep", "content": "ada's favorite tea", "person_id": ada_id},
    ).json()
    bob_memory = test_client.post(
        "/api/data/memories",
        json={"layer": "deep", "content": "bob's favorite coffee", "person_id": bob_id},
    ).json()
    general_memory = test_client.post(
        "/api/data/memories", json={"layer": "deep", "content": "general fact"}
    ).json()

    response = test_client.delete(f"/api/data/people/{ada_id}")
    assert response.status_code == 200
    assert response.json()["archived_memories"] == 1

    remaining = test_client.get("/api/data/memories", params={"person": "all"}).json()["memories"]
    remaining_ids = {m["id"] for m in remaining}
    assert remaining_ids == {bob_memory["id"], general_memory["id"]}

    archived = test_client.get("/api/data/archive").json()["archive"]
    assert len(archived) == 1
    assert archived[0]["memory_id"] == ada_memory["id"]
    assert archived[0]["reason"] == "person_deleted"

    restore_resp = test_client.post(f"/api/data/archive/{archived[0]['id']}/restore")
    assert restore_resp.status_code == 200
    restored_id = restore_resp.json()["memory_id"]

    restored_memory = next(
        m
        for m in test_client.get("/api/data/memories", params={"person": "all"}).json()[
            "memories"
        ]
        if m["id"] == restored_id
    )
    assert restored_memory["person_id"] is None


def test_delete_person_missing_returns_404(client):
    test_client, _ = client
    response = test_client.delete("/api/data/people/999")
    assert response.status_code == 404


def test_delete_person_atomic_when_archiving_fails(client, monkeypatch):
    test_client, db_path = client
    person_id = _add_person(db_path, "Ada")
    memory = test_client.post(
        "/api/data/memories",
        json={"layer": "deep", "content": "ada's memory", "person_id": person_id},
    ).json()

    def _boom(cursor, pid, *, now=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(memory_archive, "archive_person_memories", _boom)

    result = people_tool_module.delete_person(person_id)
    assert result["success"] is False

    connection = sqlite3.connect(str(db_path))
    person_row = connection.execute(
        "SELECT id FROM people WHERE id = ?", (person_id,)
    ).fetchone()
    memory_row = connection.execute(
        "SELECT id FROM memories WHERE id = ?", (memory["id"],)
    ).fetchone()
    connection.close()

    assert person_row is not None
    assert memory_row is not None


# ---- notes deletion ------------------------------------------------------------------


def test_delete_note_not_installed_returns_404(client, monkeypatch):
    test_client, _ = client
    monkeypatch.setattr(dashboard_module.toolbox_manager, "is_installed", lambda package_id: False)

    response = test_client.delete("/api/data/notes/5")
    assert response.status_code == 404


def test_delete_note_installed(client, monkeypatch):
    test_client, _ = client
    monkeypatch.setattr(dashboard_module.toolbox_manager, "is_installed", lambda package_id: True)

    def _fake_delete_note(note_id: int) -> dict:
        if note_id == 5:
            return {"success": True, "message": "Note deleted successfully."}
        return {"success": False, "error": f"ID {note_id} not found."}

    fake_package = types.ModuleType("toolbox.custom.notes")
    fake_notes_tool = types.ModuleType("toolbox.custom.notes.notes_tool")
    fake_notes_tool.delete_note = _fake_delete_note
    monkeypatch.setitem(sys.modules, "toolbox.custom.notes", fake_package)
    monkeypatch.setitem(sys.modules, "toolbox.custom.notes.notes_tool", fake_notes_tool)

    response = test_client.delete("/api/data/notes/5")
    assert response.status_code == 200
    assert response.json() == {"success": True}

    missing_response = test_client.delete("/api/data/notes/999")
    assert missing_response.status_code == 404


# ---- consolidation --------------------------------------------------------------------


def test_get_consolidation_status_shape(client):
    test_client, _ = client
    response = test_client.get("/api/memory/consolidation")
    assert response.status_code == 200
    data = response.json()
    assert set(data["policy"].keys()) == set(memory_policy.MemoryPolicy().as_dict().keys())
    assert data["running"] is False
    assert data["scheduler"]["active"] is False
    assert data["runs"] == []


def test_run_consolidation_dry_run_then_real_run(client):
    test_client, _ = client
    dry = test_client.post("/api/memory/consolidation/run", json={"dry_run": True})
    assert dry.status_code == 200
    dry_data = dry.json()
    assert dry_data["dry_run"] is True
    assert dry_data["run_id"] is None

    after_dry = test_client.get("/api/memory/consolidation").json()
    assert after_dry["runs"] == []

    real = test_client.post("/api/memory/consolidation/run", json={"dry_run": False})
    assert real.status_code == 200
    real_data = real.json()
    assert real_data["dry_run"] is False
    assert real_data["run_id"] is not None

    after_real = test_client.get("/api/memory/consolidation").json()
    assert any(run["id"] == real_data["run_id"] for run in after_real["runs"])


def test_run_consolidation_busy_returns_409(client):
    test_client, _ = client
    acquired = memory_consolidation._run_lock.acquire(blocking=False)
    assert acquired
    try:
        response = test_client.post("/api/memory/consolidation/run", json={"dry_run": True})
        assert response.status_code == 409
    finally:
        memory_consolidation._run_lock.release()


# ---- stats --------------------------------------------------------------------------


def test_stats_includes_archived_count_and_last_consolidation(client):
    test_client, _ = client
    created = test_client.post(
        "/api/data/memories", json={"layer": "deep", "content": "keep me"}
    ).json()
    memory_id = created["id"]

    stats_before = test_client.get("/api/data/memories/stats").json()
    assert stats_before["archived_count"] == 0
    assert stats_before["last_consolidation"] is None

    test_client.post(f"/api/data/memories/{memory_id}/archive")
    test_client.post("/api/memory/consolidation/run", json={"dry_run": False})

    stats_after = test_client.get("/api/data/memories/stats").json()
    assert stats_after["archived_count"] == 1
    assert stats_after["last_consolidation"] is not None
    assert stats_after["last_consolidation"]["triggered_by"] == "manual"
