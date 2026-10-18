import os
import stat

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import main
from app.config import Settings
from toolbox.db import restrict_permissions

TOKEN = "t" * 32

_REQUIRED = {
    "flash_model": "m",
    "flash_model_url": "http://localhost/v1",
    "flash_model_api": "k",
}


def _settings(token: str) -> Settings:
    return Settings(_env_file=None, auth_token=token, **_REQUIRED)


@pytest.mark.parametrize("bad", ["", "   ", "x" * 31, " " + "x" * 31 + " "])
def test_settings_rejects_short_tokens(bad):
    with pytest.raises(ValidationError, match="rona edit auth"):
        _settings(bad)


def test_settings_accepts_and_strips_token():
    assert _settings("x" * 32).auth_token == "x" * 32
    assert _settings(f"  {TOKEN}\n").auth_token == TOKEN


def test_config_defaults_are_safe(monkeypatch):
    # toolbox.packages load_dotenv()s the developer's .env into os.environ.
    for name in ("HOST", "RELOAD", "SSL_CERTFILE", "SSL_KEYFILE"):
        monkeypatch.delenv(name, raising=False)
    settings = _settings(TOKEN)
    assert settings.host == "127.0.0.1"
    assert settings.reload is False
    assert settings.ssl_certfile == ""
    assert settings.ssl_keyfile == ""


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "settings", _settings(TOKEN))
    app = FastAPI(dependencies=[Depends(main.verify_bearer_token)])

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    return TestClient(app)


def test_correct_token_passes(client):
    assert client.get("/ping", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200


@pytest.mark.parametrize(
    "header",
    [
        f"Bearer {'u' * 32}",
        "Bearer ",
        "Bearer",
        "Bearer çğü",
        f"Basic {TOKEN}",
    ],
)
def test_bad_authorization_is_401(client, header):
    response = client.get("/ping", headers={"Authorization": header.encode("utf-8")})
    assert response.status_code == 401


def test_missing_header_is_401(client):
    assert client.get("/ping").status_code == 401


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_restrict_permissions_sets_0600(tmp_path):
    path = tmp_path / "x.db"
    path.write_text("data")
    path.chmod(0o644)
    restrict_permissions(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_restrict_permissions_ignores_missing_file(tmp_path):
    restrict_permissions(tmp_path / "missing")
