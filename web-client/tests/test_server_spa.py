import os

from fastapi.testclient import TestClient

import webui.server as server_module
from webui.config import Settings

FAKE_INDEX_HTML = """\
<!doctype html>
<html lang="tr">
  <head>
    <meta charset="UTF-8" />
  </head>
  <body>
    <div id="root"></div>
  </body>
</html>
"""


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, auth_token="test-token", **overrides)


def _reset_cache(monkeypatch):
    # _index_html_cache is module-global and computed once per process --
    # tests that want a specific language must reset it first, or they'd
    # see whatever an earlier test (or the real server) already cached.
    monkeypatch.setattr(server_module, "_index_html_cache", None)


def test_localized_index_html_substitutes_lang_attribute(tmp_path, monkeypatch):
    _reset_cache(monkeypatch)
    (tmp_path / "index.html").write_text(FAKE_INDEX_HTML, encoding="utf-8")
    monkeypatch.setattr(server_module, "DIST_DIR", tmp_path)
    monkeypatch.setattr(server_module, "get_settings", lambda: _settings(ui_language="en"))

    content = server_module._localized_index_html()

    assert '<html lang="en">' in content
    assert '<html lang="tr">' not in content


def test_localized_index_html_injects_window_rona_lang(tmp_path, monkeypatch):
    _reset_cache(monkeypatch)
    (tmp_path / "index.html").write_text(FAKE_INDEX_HTML, encoding="utf-8")
    monkeypatch.setattr(server_module, "DIST_DIR", tmp_path)
    monkeypatch.setattr(server_module, "get_settings", lambda: _settings(ui_language="en"))

    content = server_module._localized_index_html()

    assert 'window.__RONA_LANG__ = "en";' in content


def test_localized_index_html_defaults_to_tr(tmp_path, monkeypatch):
    _reset_cache(monkeypatch)
    (tmp_path / "index.html").write_text(FAKE_INDEX_HTML, encoding="utf-8")
    monkeypatch.setattr(server_module, "DIST_DIR", tmp_path)
    monkeypatch.setattr(server_module, "get_settings", lambda: _settings())

    content = server_module._localized_index_html()

    assert '<html lang="tr">' in content
    assert 'window.__RONA_LANG__ = "tr";' in content


def test_localized_index_html_is_cached_across_calls(tmp_path, monkeypatch):
    _reset_cache(monkeypatch)
    (tmp_path / "index.html").write_text(FAKE_INDEX_HTML, encoding="utf-8")
    monkeypatch.setattr(server_module, "DIST_DIR", tmp_path)
    calls = []

    def _tracked_settings():
        calls.append(1)
        return _settings(ui_language="en")

    monkeypatch.setattr(server_module, "get_settings", _tracked_settings)

    first = server_module._localized_index_html()
    second = server_module._localized_index_html()

    assert first == second
    assert len(calls) == 1


def test_localized_index_html_missing_dist_returns_none(tmp_path, monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr(server_module, "DIST_DIR", tmp_path)  # empty, no index.html
    monkeypatch.setattr(server_module, "get_settings", lambda: _settings())

    assert server_module._localized_index_html() is None


def test_localized_index_html_rereads_after_a_rebuild(tmp_path, monkeypatch):
    # A rebuild while the server keeps running replaces index.html (and
    # deletes the hashed assets the old one pointed at) -- the cache must
    # notice, or every browser gets an index.html whose scripts now 404.
    _reset_cache(monkeypatch)
    index_path = tmp_path / "index.html"
    index_path.write_text(FAKE_INDEX_HTML, encoding="utf-8")
    os.utime(index_path, (1000, 1000))
    monkeypatch.setattr(server_module, "DIST_DIR", tmp_path)
    monkeypatch.setattr(server_module, "get_settings", lambda: _settings())
    server_module._localized_index_html()

    rebuilt = FAKE_INDEX_HTML.replace('<div id="root">', '<div id="root" data-build="2">')
    index_path.write_text(rebuilt, encoding="utf-8")
    os.utime(index_path, (2000, 2000))

    assert 'data-build="2"' in server_module._localized_index_html()


def test_spa_fallback_tells_browsers_to_revalidate_index_html(tmp_path, monkeypatch):
    _reset_cache(monkeypatch)
    (tmp_path / "index.html").write_text(FAKE_INDEX_HTML, encoding="utf-8")
    monkeypatch.setattr(server_module, "DIST_DIR", tmp_path)
    monkeypatch.setattr(server_module, "get_settings", lambda: _settings())
    client = TestClient(server_module.create_app(), base_url="http://localhost")

    response = client.get("/any/spa/route")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


# -- root-level PWA files (manifest, sw.js, offline.html, favicon) --------------


def test_root_static_file_serves_a_whitelisted_file(tmp_path, monkeypatch):
    (tmp_path / "sw.js").write_text("self.addEventListener('fetch', () => {});", encoding="utf-8")
    monkeypatch.setattr(server_module, "DIST_DIR", tmp_path)

    response = server_module._root_static_file("sw.js")

    assert response is not None
    assert response.media_type == "text/javascript"
    assert response.headers["cache-control"] == "no-cache"


def test_root_static_file_returns_none_outside_the_whitelist(tmp_path, monkeypatch):
    (tmp_path / "secrets.env").write_text("TOKEN=x", encoding="utf-8")
    monkeypatch.setattr(server_module, "DIST_DIR", tmp_path)

    assert server_module._root_static_file("secrets.env") is None


def test_root_static_file_returns_none_when_the_file_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "DIST_DIR", tmp_path)

    assert server_module._root_static_file("sw.js") is None


def test_manifest_is_served_with_its_media_type_and_no_cache(tmp_path, monkeypatch):
    (tmp_path / "manifest.webmanifest").write_text('{"name": "Rona"}', encoding="utf-8")
    monkeypatch.setattr(server_module, "DIST_DIR", tmp_path)
    client = TestClient(server_module.create_app(), base_url="http://localhost")

    response = client.get("/manifest.webmanifest")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")
    assert response.headers["cache-control"] == "no-cache"
    assert response.json() == {"name": "Rona"}


def test_sw_js_is_served_with_no_cache(tmp_path, monkeypatch):
    (tmp_path / "sw.js").write_text("self.addEventListener('fetch', () => {});", encoding="utf-8")
    monkeypatch.setattr(server_module, "DIST_DIR", tmp_path)
    client = TestClient(server_module.create_app(), base_url="http://localhost")

    response = client.get("/sw.js")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert "addEventListener" in response.text


def test_offline_html_is_served(tmp_path, monkeypatch):
    (tmp_path / "offline.html").write_text("<!doctype html><title>offline</title>", encoding="utf-8")
    monkeypatch.setattr(server_module, "DIST_DIR", tmp_path)
    client = TestClient(server_module.create_app(), base_url="http://localhost")

    response = client.get("/offline.html")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"


def test_a_path_not_on_the_whitelist_falls_back_to_the_spa(tmp_path, monkeypatch):
    _reset_cache(monkeypatch)
    (tmp_path / "index.html").write_text(FAKE_INDEX_HTML, encoding="utf-8")
    monkeypatch.setattr(server_module, "DIST_DIR", tmp_path)
    monkeypatch.setattr(server_module, "get_settings", lambda: _settings())
    client = TestClient(server_module.create_app(), base_url="http://localhost")

    response = client.get("/robots.txt")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_a_whitelisted_name_missing_from_dist_falls_back_to_the_spa(tmp_path, monkeypatch):
    # sw.js is a real (whitelisted) filename, but this build simply never
    # produced one -- _root_static_file must say "no" rather than 404,
    # letting the ordinary SPA fallback handle it like any other route.
    _reset_cache(monkeypatch)
    (tmp_path / "index.html").write_text(FAKE_INDEX_HTML, encoding="utf-8")
    monkeypatch.setattr(server_module, "DIST_DIR", tmp_path)
    monkeypatch.setattr(server_module, "get_settings", lambda: _settings())
    client = TestClient(server_module.create_app(), base_url="http://localhost")

    response = client.get("/sw.js")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_icons_directory_is_mounted_when_present(tmp_path, monkeypatch):
    _reset_cache(monkeypatch)
    icons_dir = tmp_path / "icons"
    icons_dir.mkdir()
    (icons_dir / "icon-192.png").write_bytes(b"\x89PNG\r\n fake")
    (tmp_path / "index.html").write_text(FAKE_INDEX_HTML, encoding="utf-8")
    monkeypatch.setattr(server_module, "DIST_DIR", tmp_path)
    monkeypatch.setattr(server_module, "get_settings", lambda: _settings())
    client = TestClient(server_module.create_app(), base_url="http://localhost")

    response = client.get("/icons/icon-192.png")

    assert response.status_code == 200
    assert response.content == b"\x89PNG\r\n fake"
