from installer import i18n
from installer.locales import en, tr


def test_catalogs_define_exactly_the_same_keys():
    assert set(tr.STRINGS) == set(en.STRINGS)


def test_catalogs_are_non_empty():
    assert len(tr.STRINGS) > 50
    assert len(en.STRINGS) > 50


def test_default_language_is_tr():
    assert i18n.DEFAULT_LANGUAGE == "tr"
    assert i18n.get_language() == "tr"


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
    assert i18n.t("prereq.not_found", name="Node.js") == "Node.js not found."


def test_t_falls_back_to_the_other_language_when_key_missing(monkeypatch):
    assert "test.only_in_en" not in tr.STRINGS
    monkeypatch.setitem(en.STRINGS, "test.only_in_en", "english fallback")
    i18n.set_language("tr")
    assert i18n.t("test.only_in_en") == "english fallback"


def test_t_falls_back_to_the_bare_key_when_missing_everywhere():
    i18n.set_language("tr")
    assert i18n.t("test.totally_unknown_key") == "test.totally_unknown_key"


def test_ask_language_default_choice_is_tr(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    assert i18n.ask_language() == "tr"


def test_ask_language_explicit_1_is_tr(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "1")
    assert i18n.ask_language() == "tr"


def test_ask_language_2_is_en(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "2")
    assert i18n.ask_language() == "en"


def test_ask_language_reprompts_on_invalid_input(monkeypatch):
    responses = iter(["bogus", "2"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))
    assert i18n.ask_language() == "en"


def test_ask_language_eof_defaults_to_tr(monkeypatch):
    def _raise(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise)
    assert i18n.ask_language() == "tr"
