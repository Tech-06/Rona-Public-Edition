import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.dashboard as dashboard_module
import create_db
from toolbox import db as toolbox_db
from toolbox.tools import mem_tool as mem_tool_module


def _fake_embedding(text: str, task_type: str) -> list[float]:
    """Deterministic stand-in for the real Gemini embedding call -- length
    encodes enough "shape" that cosine similarity is not degenerate, and
    two calls for the same text produce identical vectors (so an edited
    memory can be re-searched consistently)."""
    return [float(len(text) % 7 + 1), float(len(text) % 5 + 1), 1.0]


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "rona.db"
    sqlite3.connect(str(db_path)).close()
    monkeypatch.setattr(toolbox_db, "DB_PATH", db_path)
    monkeypatch.setattr(create_db, "DB_PATH", db_path)
    create_db.create_database()
    monkeypatch.setattr(mem_tool_module, "_get_embedding", _fake_embedding)

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


def test_create_memory_then_appears_in_list(client):
    test_client, _ = client
    response = test_client.post(
        "/api/data/memories", json={"layer": "short", "content": "loves tea"}
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    memory_id = response.json()["id"]

    listed = test_client.get("/api/data/memories").json()["memories"]
    assert len(listed) == 1
    assert listed[0]["id"] == memory_id
    assert listed[0]["layer"] == "short"
    assert listed[0]["content"] == "loves tea"


def test_create_memory_invalid_layer_returns_400(client):
    test_client, _ = client
    response = test_client.post(
        "/api/data/memories", json={"layer": "not-a-layer", "content": "x"}
    )
    assert response.status_code == 400


def test_create_memory_with_unknown_person_returns_404(client):
    test_client, _ = client
    response = test_client.post(
        "/api/data/memories",
        json={"layer": "deep", "content": "x", "person_id": 999},
    )
    assert response.status_code == 404


def test_update_memory_changes_content(client):
    test_client, _ = client
    created = test_client.post(
        "/api/data/memories", json={"layer": "short", "content": "old"}
    ).json()
    memory_id = created["id"]

    response = test_client.put(
        f"/api/data/memories/{memory_id}", json={"content": "new"}
    )
    assert response.status_code == 200

    listed = test_client.get("/api/data/memories").json()["memories"]
    assert listed[0]["content"] == "new"


def test_update_memory_missing_id_returns_404(client):
    test_client, _ = client
    response = test_client.put("/api/data/memories/999", json={"content": "x"})
    assert response.status_code == 404


def test_delete_memory_removes_it(client):
    test_client, _ = client
    created = test_client.post(
        "/api/data/memories", json={"layer": "short", "content": "temp"}
    ).json()
    memory_id = created["id"]

    response = test_client.delete(f"/api/data/memories/{memory_id}")
    assert response.status_code == 200
    assert test_client.get("/api/data/memories").json()["memories"] == []


def test_delete_memory_missing_id_returns_404(client):
    test_client, _ = client
    response = test_client.delete("/api/data/memories/999")
    assert response.status_code == 404


def test_search_memories_returns_results_ordered_by_score(client):
    test_client, _ = client
    test_client.post("/api/data/memories", json={"layer": "short", "content": "aa"})
    test_client.post("/api/data/memories", json={"layer": "short", "content": "aaaaaaa"})

    response = test_client.get("/api/data/memories/search", params={"q": "aa"})
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 2
    assert results[0]["score"] >= results[1]["score"]


def test_search_memories_requires_query(client):
    test_client, _ = client
    # `q` is a required query parameter -- omitting it entirely is a 422
    # from FastAPI's own validation, not the tool's "query required" 400.
    response = test_client.get("/api/data/memories/search")
    assert response.status_code == 422


def test_memory_stats_reports_counts_by_layer(client, tmp_path):
    test_client, db_path = client
    person_id = _add_person(db_path)
    test_client.post(
        "/api/data/memories",
        json={"layer": "deep", "content": "a", "person_id": person_id},
    )
    test_client.post("/api/data/memories", json={"layer": "short", "content": "b"})
    test_client.post("/api/data/memories", json={"layer": "short", "content": "c"})

    response = test_client.get("/api/data/memories/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert data["by_layer"] == {"deep": 1, "seasonal": 0, "short": 2}
    assert data["general_count"] == 2
    assert data["person_linked_count"] == 1


def test_memory_stats_empty_db_does_not_error(client):
    test_client, _ = client
    response = test_client.get("/api/data/memories/stats")
    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert response.json()["by_layer"] == {"deep": 0, "seasonal": 0, "short": 0}
