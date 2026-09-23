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
