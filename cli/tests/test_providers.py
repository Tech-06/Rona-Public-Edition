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
