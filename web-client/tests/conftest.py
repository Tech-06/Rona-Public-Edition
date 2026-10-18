"""Shared fixtures for the dashboard's tests.

The AUTH_TOKEN env var is set *before* anything imports webui: server.py
builds Settings at import time, a developer's real web-client/.env may hold
an old short token, and AUTH_TOKEN now needs >= 32 characters. Environment
variables outrank the .env file, so this makes the suite independent of it.
"""

import os

TEST_AUTH_TOKEN = "t" * 32
os.environ["AUTH_TOKEN"] = TEST_AUTH_TOKEN
for _name in ("WEB_PASSWORD_HASH", "WEB_SESSION_SECRET"):
    os.environ.pop(_name, None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import webui.server as server_module  # noqa: E402
from webui import auth  # noqa: E402
from webui.config import Settings  # noqa: E402

PASSWORD = "correct horse battery staple"
SESSION_SECRET = "test-session-secret-0123456789abcdef"


@pytest.fixture(scope="session")
def password_hash() -> str:
    # scrypt is deliberately slow; hash once per run.
    return auth.hash_password(PASSWORD)


@pytest.fixture(autouse=True)
def isolated_auth_state(monkeypatch, tmp_path, password_hash):
    """Point the credentials at a throwaway .env holding a known password,
    and never let a developer's real web-client/.env or Settings leak in."""
    env_path = tmp_path / "web.env"
    env_path.write_text(
        f"WEB_PASSWORD_HASH={password_hash}\nWEB_SESSION_SECRET={SESSION_SECRET}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(auth, "ENV_PATH", env_path)
    monkeypatch.setattr(auth, "_env_cache", None)
    monkeypatch.setattr(auth, "_ephemeral_secret", None)
    monkeypatch.setattr(auth, "_failures", {})
    monkeypatch.setattr(
        auth, "get_settings", lambda: Settings(_env_file=None, auth_token=TEST_AUTH_TOKEN)
    )
    return env_path


@pytest.fixture
def env_path(isolated_auth_state):
    return isolated_auth_state


@pytest.fixture
def client():
    """An app client that has NOT logged in."""
    return TestClient(server_module.create_app(), base_url="http://localhost")


@pytest.fixture
def authed_client(client):
    response = client.post("/auth/login", json={"password": PASSWORD})
    assert response.status_code == 200
    return client
