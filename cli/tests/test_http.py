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


def test_backend_base_url_scheme_wildcard_and_ipv6():
    from rona_cli import backend_client as bc

    assert bc.backend_base_url({}) == "http://127.0.0.1:8000"
    assert bc.backend_base_url({"HOST": "0.0.0.0", "PORT": "9"}) == "http://127.0.0.1:9"
    assert bc.backend_base_url({"HOST": "::"}) == "http://127.0.0.1:8000"
    assert bc.backend_base_url({"HOST": "::1"}) == "http://[::1]:8000"
    tls = {"SSL_CERTFILE": "c.pem", "SSL_KEYFILE": "k.pem"}
    assert bc.backend_base_url({**tls, "HOST": "::1"}) == "https://[::1]:8000"
    assert bc.backend_base_url({**tls, "HOST": "10.0.0.5", "PORT": "443"}) == "https://10.0.0.5:443"
    # both keys are required, as in the backend
    assert bc.backend_base_url({"SSL_CERTFILE": "c.pem", "SSL_KEYFILE": " "}).startswith("http://")


def _https_handler(client):
    return [h for h in client._opener().handlers if isinstance(h, urllib.request.HTTPSHandler)]


def test_loopback_https_uses_unverified_context_and_no_proxy():
    import ssl

    from rona_cli import backend_client as bc

    env = {"SSL_CERTFILE": "c", "SSL_KEYFILE": "k", "HOST": "0.0.0.0"}
    client = bc.make_client(env, token="t", timeout=1)
    assert client.base_url == "https://127.0.0.1:8000"
    (handler,) = _https_handler(client)
    assert handler._context.verify_mode == ssl.CERT_NONE
    assert not handler._context.check_hostname
    proxies = [h for h in client._opener().handlers if isinstance(h, urllib.request.ProxyHandler)]
    assert all(h.proxies == {} for h in proxies)


def test_remote_https_keeps_verification_and_http_has_no_context():
    from rona_cli import backend_client as bc

    remote = bc.make_client({"SSL_CERTFILE": "c", "SSL_KEYFILE": "k", "HOST": "10.0.0.5"}, token="t", timeout=1)
    assert remote.ssl_context is None
    plain = bc.make_client({}, token="t", timeout=1)
    assert plain.ssl_context is None
