from installer import ui


def _options():
    return [
        ("cli", "CLI", True, ""),
        ("backend", "Backend", True, "kurulu"),
        ("web", "Web", True, ""),
    ]


def test_select_components_empty_input_keeps_defaults(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    assert ui.select_components(_options()) == ["cli", "backend", "web"]


def test_select_components_toggles_off_then_confirms(monkeypatch):
    responses = iter(["2", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))
    assert ui.select_components(_options()) == ["cli", "web"]


def test_select_components_toggle_twice_returns_to_original(monkeypatch):
    responses = iter(["3", "3", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))
    assert ui.select_components(_options()) == ["cli", "backend", "web"]


def test_select_components_accepts_comma_and_space_separated(monkeypatch):
    responses = iter(["1,2 3", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))
    assert ui.select_components(_options()) == []


def test_select_components_ignores_out_of_range_and_non_numeric(monkeypatch):
    responses = iter(["99 abc 1", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))
    assert ui.select_components(_options()) == ["backend", "web"]


def test_select_components_eof_confirms_current_selection(monkeypatch):
    def _raise(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise)
    assert ui.select_components(_options()) == ["cli", "backend", "web"]


def test_confirm_default_false_on_eof(monkeypatch):
    def _raise(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise)
    assert ui.confirm("devam?", default=True) is False


def test_confirm_accepts_turkish_and_english_yes(monkeypatch):
    for answer in ("e", "evet", "y", "yes", "E"):
        monkeypatch.setattr("builtins.input", lambda prompt="", a=answer: a)
        assert ui.confirm("devam?") is True


def test_confirm_blank_uses_default(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    assert ui.confirm("devam?", default=True) is True
    assert ui.confirm("devam?", default=False) is False
