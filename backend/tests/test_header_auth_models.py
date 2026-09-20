"""A model reached through a gateway that authenticates on a custom header
rather than a bearer token.

FLASH_MODEL_HEADERS/PRO_MODEL_HEADERS exist precisely so a provider can be
authenticated that way, and the installer's wizard accepts an empty API key
-- but three places still treated "no api key" as "not configured", and one
of them took the whole backend down at import.
"""

import importlib

import pytest

from app.config import Settings

HEADER_AUTH_ENV = {
    "auth_token": "test-token",
    "flash_model": "gateway-flash",
    "flash_model_url": "https://gateway.example.com/v1",
    "flash_model_api": "",
    "flash_model_headers": '{"x-session": "abc"}',
    "pro_model": "gateway-pro",
    "pro_model_url": "https://gateway.example.com/v1",
    "pro_model_api": "",
    "pro_model_headers": '{"x-session": "abc"}',
}


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**HEADER_AUTH_ENV, **overrides})


def test_a_model_without_an_api_key_still_counts_as_configured():
    settings = _settings()
    assert settings.pro_configured is True


def test_a_model_without_a_url_is_still_unconfigured():
    assert _settings(pro_model_url="").pro_configured is False
    assert _settings(pro_model="").pro_configured is False


def test_llm_module_imports_with_a_blank_api_key(monkeypatch):
    """The regression that mattered: AsyncOpenAI refuses to construct without
    credentials, and these clients are built at import time -- so a blank key
    meant the backend never started at all."""
    import app.config as config_module
    import app.llm as llm_module

    monkeypatch.setattr(config_module, "get_settings", lambda: _settings())
    reloaded = importlib.reload(llm_module)

    assert reloaded.client is not None
    assert reloaded.pro_client is not None
    # The credential the gateway actually wants is still handed over.
    assert reloaded.client.default_headers["x-session"] == "abc"
    assert reloaded.pro_client.default_headers["x-session"] == "abc"

    # Put the module back the way the rest of the suite expects to find it.
    monkeypatch.undo()
    importlib.reload(llm_module)


def test_a_real_api_key_is_passed_through_untouched(monkeypatch):
    import app.config as config_module
    import app.llm as llm_module

    monkeypatch.setattr(
        config_module, "get_settings", lambda: _settings(flash_model_api="sk-real")
    )
    reloaded = importlib.reload(llm_module)
    assert reloaded.client.api_key == "sk-real"

    monkeypatch.undo()
    importlib.reload(llm_module)


@pytest.mark.parametrize("field", ["flash_model_api", "pro_model_api"])
def test_a_blank_key_becomes_a_placeholder_not_an_empty_string(monkeypatch, field):
    import app.config as config_module
    import app.llm as llm_module

    monkeypatch.setattr(config_module, "get_settings", lambda: _settings())
    reloaded = importlib.reload(llm_module)
    which = reloaded.client if field == "flash_model_api" else reloaded.pro_client
    assert which.api_key == llm_module._PLACEHOLDER_API_KEY

    monkeypatch.undo()
    importlib.reload(llm_module)
