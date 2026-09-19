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
