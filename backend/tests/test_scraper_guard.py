from toolbox.tools.web_scraper import _blocked_reason


def test_blocks_loopback():
    assert _blocked_reason("http://127.0.0.1/") is not None
    assert _blocked_reason("http://localhost/") is not None


def test_blocks_rfc1918_private_ranges():
    assert _blocked_reason("http://10.0.0.1/") is not None
    assert _blocked_reason("http://172.16.0.1/") is not None
    assert _blocked_reason("http://192.168.1.1/") is not None


def test_blocks_link_local_and_cloud_metadata_address():
    assert _blocked_reason("http://169.254.169.254/") is not None


def test_blocks_tailscale_cgnat_range():
    assert _blocked_reason("http://100.64.0.5/") is not None
    assert _blocked_reason("http://100.100.100.100/") is not None


def test_allows_addresses_outside_the_cgnat_range():
    assert _blocked_reason("http://100.63.255.255/") is None
    assert _blocked_reason("http://100.128.0.1/") is None


def test_rejects_non_http_schemes():
    assert _blocked_reason("file:///etc/passwd") is not None
    assert _blocked_reason("ftp://example.com/") is not None


def test_allows_a_public_address():
    assert _blocked_reason("http://8.8.8.8/") is None


# --- fetch hardening (no real network: getaddrinfo patched, MockTransport) ---

import socket

import httpx
import pytest

from toolbox.tools import web_scraper as ws

PUBLIC_IP = "93.184.216.34"


def _addrinfo(*ips):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]


@pytest.fixture
def fake_net(monkeypatch):
    """Patch DNS and the transport seam; records pinned IPs and requests."""
    state = {"pinned": [], "requests": [], "handler": None, "dns": [[PUBLIC_IP]]}

    def getaddrinfo(host, port, *args, **kwargs):
        answers = state["dns"]
        ips = answers.pop(0) if len(answers) > 1 else answers[0]
        return _addrinfo(*ips)

    def factory(pinned_ip):
        state["pinned"].append(pinned_ip)

        def handler(request):
            state["requests"].append(request)
            return state["handler"](request)

        return httpx.MockTransport(handler)

    monkeypatch.setattr(ws.socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(ws, "_transport_factory", factory)
    return state


def _html(body="<html><head><title>T</title></head><body>hello</body></html>", ctype="text/html"):
    return lambda request: httpx.Response(200, headers={"content-type": ctype}, content=body.encode())


def test_rebinding_second_resolution_is_never_used(fake_net):
    fake_net["dns"] = [[PUBLIC_IP], ["127.0.0.1"]]
    fake_net["handler"] = _html()
    result = ws.web_scraper("http://example.com/")
    assert result["success"] is True
    # The transport is pinned to the validated address; DNS is not consulted again.
    assert fake_net["pinned"] == [PUBLIC_IP]


def test_all_resolved_addresses_must_be_public(fake_net):
    fake_net["dns"] = [[PUBLIC_IP, "10.0.0.1"]]
    fake_net["handler"] = _html()
    result = ws.web_scraper("http://example.com/")
    assert result["success"] is False
    assert fake_net["requests"] == []


def test_redirect_to_private_address_is_blocked(fake_net):
    fake_net["dns"] = [[PUBLIC_IP], ["169.254.169.254"]]
    fake_net["handler"] = lambda r: httpx.Response(302, headers={"location": "http://evil.test/"})
    result = ws.web_scraper("http://example.com/")
    assert result["success"] is False
    assert "Blocked" in result["error"]
    assert len(fake_net["requests"]) == 1


def test_redirect_limit(fake_net):
    fake_net["handler"] = lambda r: httpx.Response(302, headers={"location": "/again"})
    assert ws.web_scraper("http://example.com/")["error"] == "Too many redirects"


def test_pinned_transport_ignores_env_proxies_and_pins_backend(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
    transport = ws._PinnedTransport(PUBLIC_IP)
    assert isinstance(transport._pool._network_backend, ws._PinnedBackend)
    assert transport._pool._network_backend._pinned_ip == PUBLIC_IP


def test_client_is_created_without_trust_env(fake_net, monkeypatch):
    seen = {}
    real = httpx.Client

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(ws.httpx, "Client", spy)
    fake_net["handler"] = _html()
    ws.web_scraper("http://example.com/")
    assert seen["trust_env"] is False


def test_large_body_is_truncated_without_reading_everything(fake_net):
    yielded = {"n": 0}

    def stream():
        yield b"<html><head><title>Big</title></head><body>"
        for _ in range(1000):
            yielded["n"] += 1
            yield b"x" * 100_000

    fake_net["handler"] = lambda r: httpx.Response(
        200, headers={"content-type": "text/html"}, content=stream()
    )
    result = ws.web_scraper("http://example.com/")
    assert result["success"] is True
    assert result["truncated"] is True
    assert len(result["content"]) <= 5000
    assert yielded["n"] <= 25  # ~2 MB cap / 100 KB chunks, not all 100 MB


@pytest.mark.parametrize("ctype", ["application/octet-stream", "image/png"])
def test_rejects_non_text_content_types(fake_net, ctype):
    fake_net["handler"] = _html("binary", ctype)
    result = ws.web_scraper("http://example.com/")
    assert result["success"] is False
    assert "content type" in result["error"]


def test_accepts_text_plain_with_charset_param(fake_net):
    fake_net["handler"] = _html("plain words", "text/plain; charset=utf-8")
    result = ws.web_scraper("http://example.com/")
    assert result["success"] is True
    assert "plain words" in result["content"]
    assert "truncated" not in result


def test_charset_is_honoured_and_bad_bytes_replaced(fake_net):
    body = "<html><body>café</body></html>".encode("latin-1")
    fake_net["handler"] = lambda r: httpx.Response(
        200, headers={"content-type": "text/html; charset=latin-1"}, content=body
    )
    assert "café" in ws.web_scraper("http://example.com/")["content"]

    fake_net["handler"] = lambda r: httpx.Response(
        200, headers={"content-type": "text/html; charset=utf-8"}, content=b"<p>a\xffb</p>"
    )
    assert ws.web_scraper("http://example.com/")["success"] is True


def test_missing_content_type_requires_html_sniff(fake_net):
    fake_net["handler"] = lambda r: httpx.Response(200, content=b"<html><body>hi</body></html>")
    assert ws.web_scraper("http://example.com/")["success"] is True
    fake_net["handler"] = lambda r: httpx.Response(200, content=b"\x89PNG\r\n\x1a\n\x00\x00")
    assert ws.web_scraper("http://example.com/")["success"] is False


def test_rejects_credentials_and_non_http_schemes(fake_net):
    fake_net["handler"] = _html()
    for bad in ("http://user:pw@example.com/", "http://user@example.com/", "ftp://example.com/"):
        assert ws.web_scraper(bad)["success"] is False
    assert fake_net["requests"] == []


def test_tries_next_validated_address_when_first_does_not_connect(fake_net, monkeypatch):
    v6 = "2606:2800:220:1:248:1893:25c8:1946"
    fake_net["dns"] = [[v6, PUBLIC_IP]]
    tried = []

    def factory(pinned_ip):
        tried.append(pinned_ip)
        if ":" in pinned_ip:
            def boom(request):
                raise httpx.ConnectError("network unreachable")

            return httpx.MockTransport(boom)
        return httpx.MockTransport(lambda r: fake_net["handler"](r))

    monkeypatch.setattr(ws, "_transport_factory", factory)
    fake_net["handler"] = _html()
    result = ws.web_scraper("http://example.com/")
    assert result["success"] is True
    assert tried == [PUBLIC_IP]  # IPv4 first, so the dead IPv6 is never needed

    tried.clear()
    monkeypatch.setattr(ws, "_resolve_checked", lambda url: (None, [v6, PUBLIC_IP]))
    assert ws.web_scraper("http://example.com/")["success"] is True
    assert tried == [v6, PUBLIC_IP]


def test_connect_failure_on_every_address_is_an_error(fake_net, monkeypatch):
    def boom(request):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(ws, "_transport_factory", lambda ip: httpx.MockTransport(boom))
    result = ws.web_scraper("http://example.com/")
    assert result["success"] is False


@pytest.mark.parametrize(
    "ctype",
    [
        "application/json",
        "application/ld+json",
        "text/xml",
        "application/xml",
        "application/rss+xml",
        "application/atom+xml; charset=utf-8",
    ],
)
def test_structured_text_content_types_are_returned_verbatim(fake_net, ctype):
    body = '<root><item a="1">x</item></root>' if "xml" in ctype else '{"k": "v"}'
    fake_net["handler"] = _html(body, ctype)
    result = ws.web_scraper("http://example.com/")
    assert result["success"] is True
    assert result["content"] == body
