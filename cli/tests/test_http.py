import urllib.request

from rona_cli import http


def test_backend_client_ignores_proxy_env(fake_api, monkeypatch):
    """A machine-wide proxy must never see the local backend's bearer token."""
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.setenv(var, "http://127.0.0.1:9")  # nothing listens here
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    fake_api.set_route("GET", "/api/ping", 200, {"ok": True})
    client = http.Client(base_url=f"http://127.0.0.1:{fake_api.port}", token="tok")
    assert client.get("/api/ping") == {"ok": True}
    assert fake_api.requests[0]["headers"]["authorization"] == "Bearer tok"


def test_default_client_opener_has_no_proxies():
    opener = http.Client(base_url="http://127.0.0.1:1")._opener()
    handlers = [h for h in opener.handlers if isinstance(h, urllib.request.ProxyHandler)]
    assert all(h.proxies == {} for h in handlers)
    assert opener is not http._ENV_PROXY_OPENER


def test_use_proxy_client_opener_honors_env_proxies():
    assert http.Client(base_url="https://api.example.com", use_proxy=True)._opener() is http._ENV_PROXY_OPENER
    assert http.Client(base_url="http://127.0.0.1:1")._opener() is http._NO_PROXY_OPENER


def test_is_loopback_url():
    assert http.is_loopback_url("http://127.0.0.1:8000")
    assert http.is_loopback_url("http://localhost:11434/v1")
    assert http.is_loopback_url("http://[::1]:8000")
    assert not http.is_loopback_url("https://api.openai.com/v1")
    assert not http.is_loopback_url("http://10.0.0.5:8000")
