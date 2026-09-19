import json

import pytest

from rona_cli import i18n
from rona_cli.locales import en, tr


@pytest.fixture(autouse=True)
def _reset_active_language():
    """`i18n._active` is process-global state (set once in `main()`, read
    by every `t()` call) -- tests that change it must not leak that change
    into other test modules that assume the tr default."""
    original = i18n.get_language()
    yield
    i18n.set_language(original)


def test_catalogs_define_exactly_the_same_keys():
    assert set(tr.STRINGS) == set(en.STRINGS)


def test_catalogs_are_non_empty():
    assert len(tr.STRINGS) > 50
    assert len(en.STRINGS) > 50


def test_default_language_is_tr():
    assert i18n.DEFAULT_LANGUAGE == "tr"
    assert i18n.get_language() == "tr"


def test_resolve_language_env_var_takes_priority(tmp_path, monkeypatch):
    monkeypatch.setenv("RONA_LANG", "en")
    state_path = tmp_path / "config.json"
    state_path.write_text(json.dumps({"language": "tr"}), encoding="utf-8")
    monkeypatch.setattr(i18n, "state_file", lambda: state_path)
    assert i18n.resolve_language() == "en"


def test_resolve_language_falls_back_to_state_file(tmp_path, monkeypatch):
    monkeypatch.delenv("RONA_LANG", raising=False)
    state_path = tmp_path / "config.json"
    state_path.write_text(json.dumps({"language": "en"}), encoding="utf-8")
    monkeypatch.setattr(i18n, "state_file", lambda: state_path)
    assert i18n.resolve_language() == "en"


def test_resolve_language_ignores_unsupported_state_value(tmp_path, monkeypatch):
    monkeypatch.delenv("RONA_LANG", raising=False)
    state_path = tmp_path / "config.json"
    state_path.write_text(json.dumps({"language": "fr"}), encoding="utf-8")
    monkeypatch.setattr(i18n, "state_file", lambda: state_path)
    assert i18n.resolve_language() == i18n.DEFAULT_LANGUAGE


def test_resolve_language_defaults_when_nothing_set(tmp_path, monkeypatch):
    monkeypatch.delenv("RONA_LANG", raising=False)
    monkeypatch.setattr(i18n, "state_file", lambda: tmp_path / "no-such-file.json")
    assert i18n.resolve_language() == i18n.DEFAULT_LANGUAGE


def test_resolve_language_survives_corrupt_state_file(tmp_path, monkeypatch):
    monkeypatch.delenv("RONA_LANG", raising=False)
    state_path = tmp_path / "config.json"
    state_path.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(i18n, "state_file", lambda: state_path)
    assert i18n.resolve_language() == i18n.DEFAULT_LANGUAGE


def test_set_language_rejects_unsupported_value():
    i18n.set_language("fr")
    assert i18n.get_language() == i18n.DEFAULT_LANGUAGE


def test_t_returns_the_active_languages_string():
    i18n.set_language("tr")
    assert i18n.t("common.cancelled") == "Vazgeçildi."
    i18n.set_language("en")
    assert i18n.t("common.cancelled") == "Cancelled."


def test_t_formats_keyword_arguments():
    i18n.set_language("en")
    assert i18n.t("memory.added", id=42) == "Memory added (id 42)."


def test_t_falls_back_to_the_other_language_when_key_missing(monkeypatch):
    assert "test.only_in_en" not in tr.STRINGS  # sanity: genuinely absent, not overwritten
    monkeypatch.setitem(en.STRINGS, "test.only_in_en", "english fallback")
    i18n.set_language("tr")
    assert i18n.t("test.only_in_en") == "english fallback"


def test_t_falls_back_to_the_bare_key_when_missing_everywhere():
    i18n.set_language("tr")
    assert i18n.t("test.totally_unknown_key") == "test.totally_unknown_key"
