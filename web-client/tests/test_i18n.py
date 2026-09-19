import pytest

from webui import i18n
from webui.config import Settings
from webui.locales import en, tr


def test_catalogs_define_exactly_the_same_keys():
    assert set(tr.STRINGS) == set(en.STRINGS)


def test_catalogs_are_non_empty():
    assert len(tr.STRINGS) > 5
    assert len(en.STRINGS) > 5


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, auth_token="test-token", **overrides)


def test_settings_ui_language_defaults_to_tr():
    assert _settings().ui_language == "tr"


def test_settings_ui_language_accepts_en():
    assert _settings(ui_language="en").ui_language == "en"


def test_settings_ui_language_is_case_insensitive():
    assert _settings(ui_language="EN").ui_language == "en"


def test_settings_ui_language_rejects_unsupported_value():
    with pytest.raises(ValueError, match="invalid ui_language"):
        _settings(ui_language="fr")


def test_active_language_reads_from_settings(monkeypatch):
    import webui.config as config_module

    monkeypatch.setattr(config_module, "get_settings", lambda: _settings(ui_language="en"))
    assert i18n._active_language() == "en"

    monkeypatch.setattr(config_module, "get_settings", lambda: _settings(ui_language="tr"))
    assert i18n._active_language() == "tr"


def test_t_returns_the_active_languages_string(monkeypatch):
    import webui.config as config_module

    monkeypatch.setattr(config_module, "get_settings", lambda: _settings(ui_language="tr"))
    assert i18n.t("webui.backend_unreachable") == "Backend'e ulaşılamıyor"

    monkeypatch.setattr(config_module, "get_settings", lambda: _settings(ui_language="en"))
    assert i18n.t("webui.backend_unreachable") == "Backend is not reachable"


def test_t_formats_keyword_arguments(monkeypatch):
    import webui.config as config_module

    monkeypatch.setattr(config_module, "get_settings", lambda: _settings(ui_language="en"))
    assert i18n.t("webui.started_pid", pid=1234) == "Started PID 1234"


def test_t_falls_back_to_the_other_language_when_key_missing(monkeypatch):
    import webui.config as config_module

    monkeypatch.setattr(config_module, "get_settings", lambda: _settings(ui_language="tr"))
    assert "test.only_in_en" not in tr.STRINGS
    monkeypatch.setitem(en.STRINGS, "test.only_in_en", "english fallback")
    assert i18n.t("test.only_in_en") == "english fallback"


def test_t_falls_back_to_the_bare_key_when_missing_everywhere(monkeypatch):
    import webui.config as config_module

    monkeypatch.setattr(config_module, "get_settings", lambda: _settings(ui_language="tr"))
    assert i18n.t("test.totally_unknown_key") == "test.totally_unknown_key"
