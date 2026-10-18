import re

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import webui.server as server_module
from webui import proxy

REQUIRED = {
    "x-frame-options": "DENY",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "cross-origin-opener-policy": "same-origin",
}


def _assert_headers(response):
    for name, value in REQUIRED.items():
        assert response.headers[name] == value
    csp = response.headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "img-src 'self' data: blob:" in csp
    assert "camera=()" in response.headers["permissions-policy"]


@pytest.fixture
def dist(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text(
        '<!doctype html>\n<html lang="tr">\n  <head>\n'
        '    <script src="/theme-init.js"></script>\n  </head>\n  <body></body>\n</html>\n',
        encoding="utf-8",
    )
    (tmp_path / "theme-init.js").write_text("/* theme */", encoding="utf-8")
    (tmp_path / "offline.js").write_text("/* offline */", encoding="utf-8")
    monkeypatch.setattr(server_module, "DIST_DIR", tmp_path)
    monkeypatch.setattr(server_module, "_index_html_cache", None)
    return tmp_path


def _spa_client():
    return TestClient(server_module.create_app(), base_url="http://localhost")


def test_headers_on_spa_index_and_static(dist):
    client = _spa_client()
    for path in ("/", "/some/route", "/theme-init.js", "/offline.js"):
        response = client.get(path)
        assert response.status_code == 200, path
        _assert_headers(response)


def test_headers_on_auth_status_and_401(client):
    _assert_headers(client.get("/auth/status"))
    blocked = client.get("/api/anything")
    assert blocked.status_code == 401
    _assert_headers(blocked)


def test_headers_on_bad_host(client):
    response = client.get("/auth/status", headers={"host": "evil.example"})
    assert response.status_code == 400
    _assert_headers(response)


def test_headers_on_proxied_route(authed_client, monkeypatch):
    async def fake_proxy(request, path):
        return JSONResponse({"ok": True})

    monkeypatch.setattr(proxy, "proxy_request", fake_proxy)
    response = authed_client.get("/api/ping")
    assert response.status_code == 200
    _assert_headers(response)


def test_localized_index_has_meta_and_no_inline_script(dist):
    content = server_module._localized_index_html()
    assert '<meta name="rona-lang" content="tr" />' in content
    assert not re.search(r"<script(?![^>]*\bsrc=)", content)


def test_root_file_whitelist_serves_scripts(dist):
    client = _spa_client()
    for name in ("theme-init.js", "offline.js"):
        response = client.get(f"/{name}")
        assert response.headers["content-type"].startswith("text/javascript")
        assert "no-cache" in response.headers["cache-control"]
