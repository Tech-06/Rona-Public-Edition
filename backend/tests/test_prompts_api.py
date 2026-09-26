"""Tests for the /api/prompts HTTP surface (app/prompts_api.py), i.e. the
C4 contract other agents (frontend, CLI) build against. The autouse
fixture in conftest.py isolates prompt_store.CUSTOM_DIR per test.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import prompt_store, prompts_api

EXPECTED_GROUPS = {
    "persona": "main",
    "output_text": "main",
    "user": "main",
    "toolbox": "main",
    "memory": "main",
    "subagents": "main",
    "trigger": "main",
    "subagent_worker": "subagent",
    "trigger_worker": "trigger",
}


@pytest.fixture
def client():
    application = FastAPI()
    application.include_router(prompts_api.router)
    return TestClient(application)


def test_list_returns_all_nine_prompts_grouped(client):
    response = client.get("/api/prompts")
    assert response.status_code == 200
    data = response.json()
    assert data["max_bytes"] == prompt_store.MAX_PROMPT_BYTES
    by_id = {item["id"]: item for item in data["prompts"]}
    assert set(by_id) == set(EXPECTED_GROUPS)
    for prompt_id, group in EXPECTED_GROUPS.items():
        assert by_id[prompt_id]["group"] == group
        assert by_id[prompt_id]["customized"] is False
    placeholder_names = {p["name"] for p in data["placeholders"]}
    assert placeholder_names == {"PRIMARY_LANGUAGE_RULE", "EXAMPLE_GREETING"}


def test_get_prompt_returns_full_shape(client):
    response = client.get("/api/prompts/persona")
    assert response.status_code == 200
    data = response.json()
    for key in ("content", "default_content", "version", "default_version", "id", "group"):
        assert key in data
    assert data["version"] == data["default_version"]


def test_get_unknown_prompt_is_404(client):
    response = client.get("/api/prompts/nope")
    assert response.status_code == 404


def test_put_ok_updates_content_and_returns_warnings(client):
    current = client.get("/api/prompts/user").json()
    response = client.put(
        "/api/prompts/user",
        json={"content": "new user content\n", "base_version": current["version"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["content"] == "new user content\n"
    assert data["customized"] is True
    assert data["warnings"] == []

    refetched = client.get("/api/prompts/user").json()
    assert refetched["content"] == "new user content\n"
    assert refetched["customized"] is True


def test_put_stale_base_version_is_409(client):
    current = client.get("/api/prompts/user").json()
    first = client.put(
        "/api/prompts/user",
        json={"content": "first edit\n", "base_version": current["version"]},
    )
    assert first.status_code == 200

    stale = client.put(
        "/api/prompts/user",
        json={"content": "second edit\n", "base_version": current["version"]},
    )
    assert stale.status_code == 409


def test_put_invalid_content_is_422(client):
    current = client.get("/api/prompts/persona").json()
    response = client.put(
        "/api/prompts/persona",
        json={"content": "missing the placeholder\n", "base_version": current["version"]},
    )
    assert response.status_code == 422


def test_put_unknown_id_is_404(client):
    response = client.put(
        "/api/prompts/nope", json={"content": "x", "base_version": "0" * 16}
    )
    assert response.status_code == 404


def test_delete_resets_to_default(client):
    current = client.get("/api/prompts/user").json()
    client.put(
        "/api/prompts/user",
        json={"content": "custom content\n", "base_version": current["version"]},
    )
    response = client.delete("/api/prompts/user")
    assert response.status_code == 200
    data = response.json()
    assert data["customized"] is False
    assert data["content"] == data["default_content"]


def test_delete_unknown_id_is_404(client):
    response = client.delete("/api/prompts/nope")
    assert response.status_code == 404
