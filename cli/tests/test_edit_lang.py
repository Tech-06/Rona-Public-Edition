import json
from types import SimpleNamespace

from rona_cli import envio
from rona_cli.commands.edit import lang as edit_lang

from .helpers import make_root


def _args(root, **overrides):
    defaults = {
        "root": str(root),
        "json": False,
        "language": None,
        "backend": False,
        "web": False,
        "cli": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_show_defaults_to_tr_when_nothing_configured(tmp_path, monkeypatch, capsys):
    root = make_root(tmp_path)
    (root / "backend" / ".env").write_text("", encoding="utf-8")
    (root / "web-client" / ".env").write_text("", encoding="utf-8")
    monkeypatch.setattr(edit_lang, "state_file", lambda: tmp_path / "no-such-config.json")

    code = edit_lang._cmd_show(_args(root))
    assert code == 0
    out = capsys.readouterr().out
    assert "tr" in out


def test_show_json_reports_all_three(tmp_path, monkeypatch, capsys):
    root = make_root(tmp_path)
    (root / "backend" / ".env").write_text("LANGUAGE=en\n", encoding="utf-8")
    (root / "web-client" / ".env").write_text("UI_LANGUAGE=en\n", encoding="utf-8")
    state_path = tmp_path / "config.json"
    state_path.write_text(json.dumps({"language": "en"}), encoding="utf-8")
    monkeypatch.setattr(edit_lang, "state_file", lambda: state_path)

    code = edit_lang._cmd_show(_args(root, json=True))
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": True, "backend": "en", "web": "en", "cli": "en"}


def test_set_with_no_flags_writes_all_three(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    (root / "backend" / ".env").write_text("", encoding="utf-8")
    (root / "web-client" / ".env").write_text("", encoding="utf-8")
    state_path = tmp_path / "config.json"
    monkeypatch.setattr(edit_lang, "state_file", lambda: state_path)

    code = edit_lang._cmd_set(_args(root, language="en"))
    assert code == 0
    assert envio.read_env_file(root / "backend" / ".env")["LANGUAGE"] == "en"
    assert envio.read_env_file(root / "web-client" / ".env")["UI_LANGUAGE"] == "en"
    assert json.loads(state_path.read_text(encoding="utf-8"))["language"] == "en"


def test_set_with_one_flag_only_touches_that_target(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    (root / "backend" / ".env").write_text("LANGUAGE=tr\n", encoding="utf-8")
    (root / "web-client" / ".env").write_text("UI_LANGUAGE=tr\n", encoding="utf-8")
    state_path = tmp_path / "config.json"
    monkeypatch.setattr(edit_lang, "state_file", lambda: state_path)

    code = edit_lang._cmd_set(_args(root, language="en", cli=True))
    assert code == 0
    # untouched targets keep their original value
    assert envio.read_env_file(root / "backend" / ".env")["LANGUAGE"] == "tr"
    assert envio.read_env_file(root / "web-client" / ".env")["UI_LANGUAGE"] == "tr"
    assert json.loads(state_path.read_text(encoding="utf-8"))["language"] == "en"


def test_set_preserves_other_fields_in_state_file(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    (root / "backend" / ".env").write_text("", encoding="utf-8")
    (root / "web-client" / ".env").write_text("", encoding="utf-8")
    state_path = tmp_path / "config.json"
    state_path.write_text(
        json.dumps({"root": str(root), "components": {"cli": True}, "installed_at": "2026-01-01"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(edit_lang, "state_file", lambda: state_path)

    edit_lang._cmd_set(_args(root, language="en", cli=True))

    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert data["language"] == "en"
    assert data["root"] == str(root)
    assert data["components"] == {"cli": True}
    assert data["installed_at"] == "2026-01-01"


def test_set_dispatch_via_language_argument(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    (root / "backend" / ".env").write_text("", encoding="utf-8")
    (root / "web-client" / ".env").write_text("", encoding="utf-8")
    monkeypatch.setattr(edit_lang, "state_file", lambda: tmp_path / "config.json")

    code = edit_lang._dispatch(_args(root, language="en"))
    assert code == 0
    assert envio.read_env_file(root / "backend" / ".env")["LANGUAGE"] == "en"


def test_show_dispatch_when_language_omitted(tmp_path, monkeypatch, capsys):
    root = make_root(tmp_path)
    (root / "backend" / ".env").write_text("", encoding="utf-8")
    (root / "web-client" / ".env").write_text("", encoding="utf-8")
    monkeypatch.setattr(edit_lang, "state_file", lambda: tmp_path / "no-such-config.json")

    code = edit_lang._dispatch(_args(root, language=None))
    assert code == 0
    assert "tr" in capsys.readouterr().out
