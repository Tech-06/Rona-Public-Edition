import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.dashboard as dashboard_module

MINIMAL_ENV = """\
AUTH_TOKEN=test-token
FLASH_MODEL=test-model
FLASH_MODEL_URL=http://example.com
FLASH_MODEL_API=test-key
TRIGGER_TIMEZONE=UTC
LOG_LEVEL=INFO
SUBAGENT_MAX_ROUNDS=50
"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(MINIMAL_ENV, encoding="utf-8")
    monkeypatch.setattr(dashboard_module, "ENV_PATH", env_path)
    test_app = FastAPI()
    test_app.include_router(dashboard_module.router)
    return TestClient(test_app), env_path


def test_update_config_rejects_unknown_field(client):
    test_client, env_path = client
    original = env_path.read_text(encoding="utf-8")
    response = test_client.put("/api/config", json={"auth_token": "hacked"})
    assert response.status_code == 400
    assert "auth_token" in response.json()["detail"]
    assert env_path.read_text(encoding="utf-8") == original


def test_update_config_rejects_invalid_value_without_writing(client):
    test_client, env_path = client
    original = env_path.read_text(encoding="utf-8")
    response = test_client.put("/api/config", json={"trigger_timezone": "Not/AZone"})
    assert response.status_code == 400
    assert env_path.read_text(encoding="utf-8") == original


def test_update_config_writes_valid_change(client):
    test_client, env_path = client
    response = test_client.put("/api/config", json={"log_level": "DEBUG"})
    assert response.status_code == 200
    assert response.json() == {"restart_required": True}
    assert "LOG_LEVEL=DEBUG" in env_path.read_text(encoding="utf-8")


def test_update_config_preserves_unknown_lines_and_order(client):
    test_client, env_path = client
    test_client.put("/api/config", json={"subagent_max_rounds": 75})
    lines = env_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "AUTH_TOKEN=test-token"
    assert "SUBAGENT_MAX_ROUNDS=75" in lines
    assert "FLASH_MODEL_URL=http://example.com" in lines


def test_update_config_appends_previously_absent_editable_key(client):
    test_client, env_path = client
    test_client.put("/api/config", json={"web_autostart": True})
    assert "WEB_AUTOSTART=true" in env_path.read_text(encoding="utf-8").splitlines()


def test_read_config_excludes_secret_fields(client):
    test_client, _ = client
    response = test_client.get("/api/config")
    assert response.status_code == 200
    values = response.json()["values"]
    for secret_field in (
        "auth_token",
        "flash_model_api",
        "pro_model_api",
        "flash_model_headers",
        "pro_model_headers",
    ):
        assert secret_field not in values
