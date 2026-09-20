import pytest

from rona_cli import providers


def test_parse_headers_empty_returns_empty_dict():
    assert providers.parse_headers(None) == {}
    assert providers.parse_headers("") == {}
    assert providers.parse_headers("   ") == {}


def test_parse_headers_parses_json_object():
    assert providers.parse_headers('{"x-foo": "bar"}') == {"x-foo": "bar"}


def test_parse_headers_rejects_invalid_json():
    with pytest.raises(ValueError, match="JSON"):
        providers.parse_headers("not json")


def test_parse_headers_rejects_non_object_json():
    with pytest.raises(ValueError, match="obje"):
        providers.parse_headers("[1, 2, 3]")


def test_test_chat_model_missing_fields_fails_fast():
    ok, detail = providers.test_chat_model("", "key", "model")
    assert ok is False
    assert "gerekli" in detail


def test_test_chat_model_success(fake_api):
    fake_api.set_route("POST", "/chat/completions", 200, {"choices": []})
    ok, detail = providers.test_chat_model(
        f"http://127.0.0.1:{fake_api.port}", "sk-test", "test-model"
    )
    assert ok is True
    assert detail == "ok"
    request = fake_api.requests[0]
    assert request["headers"]["authorization"] == "Bearer sk-test"
    assert request["body"]["model"] == "test-model"


def test_test_chat_model_sends_extra_headers(fake_api):
    fake_api.set_route("POST", "/chat/completions", 200, {})
    providers.test_chat_model(
        f"http://127.0.0.1:{fake_api.port}", "sk-test", "test-model", {"x-org": "acme"}
    )
    assert fake_api.requests[0]["headers"]["x-org"] == "acme"


def test_test_chat_model_reports_http_error(fake_api):
    fake_api.set_route("POST", "/chat/completions", 401, {"error": "bad key"})
    ok, detail = providers.test_chat_model(
        f"http://127.0.0.1:{fake_api.port}", "sk-bad", "test-model"
    )
    assert ok is False
    assert "401" in detail


def test_test_embedding_missing_fields_fails_fast():
    ok, _detail = providers.test_embedding("", "")
    assert ok is False


def test_test_embedding_success(fake_api, monkeypatch):
    monkeypatch.setattr(providers, "GOOGLE_EMBED_BASE_URL", f"http://127.0.0.1:{fake_api.port}")
    fake_api.set_route(
        "POST", "/v1beta/models/embedding-001:embedContent", 200, {"embedding": {"values": [0.1]}}
    )
    ok, _detail = providers.test_embedding("google-key", "embedding-001")
    assert ok is True
    request = fake_api.requests[0]
    assert "key=google-key" in request["path"]


def test_test_embedding_normalizes_bare_model_name():
    assert providers._normalize_embedding_model("embedding-001") == "models/embedding-001"
    assert providers._normalize_embedding_model("models/embedding-001") == "models/embedding-001"


def test_test_embedding_reports_http_error(fake_api, monkeypatch):
    monkeypatch.setattr(providers, "GOOGLE_EMBED_BASE_URL", f"http://127.0.0.1:{fake_api.port}")
    fake_api.set_route("POST", "/v1beta/models/bad:embedContent", 403, {"error": "denied"})
    ok, detail = providers.test_embedding("bad-key", "bad")
    assert ok is False
    assert "403" in detail


def test_test_chat_model_sends_a_user_agent(fake_api):
    """Providers behind bot-protection (Cloudflare's HTTP 403 "error code:
    1010" among them) block urllib's default "Python-urllib/x.y" User-Agent
    outright -- even though the identical request the backend makes through
    the openai SDK, which sets its own, sails through unblocked."""
    fake_api.set_route("POST", "/chat/completions", 200, {})
    providers.test_chat_model(f"http://127.0.0.1:{fake_api.port}", "sk-test", "test-model")
    ua = fake_api.requests[0]["headers"]["user-agent"]
    assert ua and not ua.startswith("Python-urllib")


def test_normalize_chat_base_url_strips_a_pasted_completions_suffix():
    """Most providers document the *full* completions endpoint, which is
    exactly what people paste into FLASH_MODEL_URL -- and what the backend's
    own normalize_model_url validator already tolerates by stripping it."""
    assert (
        providers.normalize_chat_base_url("https://api.example.com/v1/chat/completions")
        == "https://api.example.com/v1"
    )
    assert (
        providers.normalize_chat_base_url("https://api.example.com/v1/chat/completions/")
        == "https://api.example.com/v1"
    )
    # Already a bare base URL: left untouched.
    assert providers.normalize_chat_base_url("https://api.example.com/v1") == "https://api.example.com/v1"


def test_test_chat_model_does_not_double_the_completions_path(fake_api):
    """Without normalizing first, a pasted full-endpoint URL would build
    <url>/chat/completions on top of a URL that already ends in
    /chat/completions -- testing a different address than the backend
    actually calls, and the wrong one entirely against a server that
    doesn't happen to tolerate the doubled path."""
    fake_api.set_route("POST", "/chat/completions", 200, {})
    ok, detail = providers.test_chat_model(
        f"http://127.0.0.1:{fake_api.port}/chat/completions", "sk-test", "test-model"
    )
    assert ok is True, detail
    assert len(fake_api.requests) == 1
