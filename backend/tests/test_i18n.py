import pytest

import i18n
from app.config import Settings
from app.prompts import _substitute_placeholders
from locales import en, tr


def test_catalogs_define_exactly_the_same_keys():
    assert set(tr.STRINGS) == set(en.STRINGS)


def test_catalogs_are_non_empty():
    assert len(tr.STRINGS) > 20
    assert len(en.STRINGS) > 20


_REQUIRED_SETTINGS_FIELDS = {
    "auth_token": "test-token",
    "flash_model": "test-model",
    "flash_model_url": "http://example.com",
    "flash_model_api": "test-key",
}


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**_REQUIRED_SETTINGS_FIELDS, **overrides})


def test_settings_language_defaults_to_tr():
    assert _settings().language == "tr"


def test_settings_language_accepts_en():
    assert _settings(language="en").language == "en"


def test_settings_language_is_case_insensitive():
    assert _settings(language="EN").language == "en"


def test_settings_language_rejects_unsupported_value():
    with pytest.raises(ValueError, match="invalid language"):
        _settings(language="fr")


def test_active_language_reads_from_settings(monkeypatch):
    import app.config as config_module

    monkeypatch.setattr(config_module, "get_settings", lambda: _settings(language="en"))
    assert i18n._active_language() == "en"

    monkeypatch.setattr(config_module, "get_settings", lambda: _settings(language="tr"))
    assert i18n._active_language() == "tr"


def test_t_returns_the_active_languages_string(monkeypatch):
    import app.config as config_module

    monkeypatch.setattr(config_module, "get_settings", lambda: _settings(language="tr"))
    assert i18n.t("dashboard.task_not_found") == "Görev bulunamadı"

    monkeypatch.setattr(config_module, "get_settings", lambda: _settings(language="en"))
    assert i18n.t("dashboard.task_not_found") == "Task not found"


def test_t_formats_keyword_arguments(monkeypatch):
    import app.config as config_module

    monkeypatch.setattr(config_module, "get_settings", lambda: _settings(language="en"))
    assert i18n.t("dashboard.invalid_kind", kind="bogus") == "invalid kind: bogus"


def test_t_without_kwargs_leaves_percent_style_placeholders_intact(monkeypatch):
    # Log-line catalog entries use %-style placeholders (consumed by
    # logging's own lazy formatting, logger.info(template, *args)) rather
    # than str.format() -- t() must hand them back untouched when called
    # with no kwargs.
    import app.config as config_module

    monkeypatch.setattr(config_module, "get_settings", lambda: _settings(language="en"))
    assert i18n.t("trigger.log_fired") == "[trigger] %s fired: %s"


def test_t_falls_back_to_the_other_language_when_key_missing(monkeypatch):
    import app.config as config_module

    monkeypatch.setattr(config_module, "get_settings", lambda: _settings(language="tr"))
    monkeypatch.setitem(en.STRINGS, "test.only_in_en", "english fallback")
    assert "test.only_in_en" not in tr.STRINGS
    assert i18n.t("test.only_in_en") == "english fallback"


def test_t_falls_back_to_the_bare_key_when_missing_everywhere(monkeypatch):
    import app.config as config_module

    monkeypatch.setattr(config_module, "get_settings", lambda: _settings(language="tr"))
    assert i18n.t("test.totally_unknown_key") == "test.totally_unknown_key"


# ---- app/prompts.py's {{...}} substitution ------------------------------------


def test_substitute_placeholders_replaces_primary_language_rule(monkeypatch):
    import app.config as config_module

    monkeypatch.setattr(config_module, "get_settings", lambda: _settings(language="en"))
    result = _substitute_placeholders("Rule: {{PRIMARY_LANGUAGE_RULE}}")
    assert "{{" not in result
    assert "English" in result


def test_substitute_placeholders_replaces_example_greeting(monkeypatch):
    import app.config as config_module

    monkeypatch.setattr(config_module, "get_settings", lambda: _settings(language="tr"))
    result = _substitute_placeholders("say '{{EXAMPLE_GREETING}}'")
    assert result == "say 'Nasılsın?'"


def test_substitute_placeholders_leaves_plain_text_untouched(monkeypatch):
    import app.config as config_module

    monkeypatch.setattr(config_module, "get_settings", lambda: _settings(language="tr"))
    assert _substitute_placeholders("no placeholders here") == "no placeholders here"
