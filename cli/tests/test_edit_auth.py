import io
from types import SimpleNamespace

from rona_cli import envio, i18n
from rona_cli.commands.edit import auth as edit_auth

from .helpers import make_root


def _args(root, **overrides):
    defaults = {"root": str(root), "json": False, "show": False, "yes": False, "token": None, "stdin": False}
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_reset_writes_matching_token_to_both_envs(tmp_path):
    root = make_root(tmp_path)
    (root / "backend" / ".env").write_text("A=1\n", encoding="utf-8")
    (root / "web-client" / ".env").write_text("B=2\n", encoding="utf-8")

    code = edit_auth._cmd_reset(_args(root, yes=True))
    assert code == 0

    backend_token = envio.read_env_file(root / "backend" / ".env")["AUTH_TOKEN"]
    web_token = envio.read_env_file(root / "web-client" / ".env")["AUTH_TOKEN"]
    assert backend_token == web_token
    assert len(backend_token) > 20
    # unrelated existing keys survive
    assert envio.read_env_file(root / "backend" / ".env")["A"] == "1"
    assert envio.read_env_file(root / "web-client" / ".env")["B"] == "2"


def test_reset_without_yes_requires_confirmation(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    (root / "backend" / ".env").write_text("AUTH_TOKEN=old\n", encoding="utf-8")
    (root / "web-client" / ".env").write_text("AUTH_TOKEN=old\n", encoding="utf-8")
    monkeypatch.setattr(edit_auth.ui, "confirm", lambda *a, **k: False)

    code = edit_auth._cmd_reset(_args(root, yes=False))
    assert code == 1
    assert envio.read_env_file(root / "backend" / ".env")["AUTH_TOKEN"] == "old"


def test_set_writes_given_token_to_both_envs(tmp_path):
    root = make_root(tmp_path)
    (root / "backend" / ".env").write_text("", encoding="utf-8")
    (root / "web-client" / ".env").write_text("", encoding="utf-8")

    code = edit_auth._cmd_set(_args(root, token="my-custom-token-0123456789-abcdefghij"))
    assert code == 0
    assert envio.read_env_file(root / "backend" / ".env")["AUTH_TOKEN"] == "my-custom-token-0123456789-abcdefghij"
    assert envio.read_env_file(root / "web-client" / ".env")["AUTH_TOKEN"] == "my-custom-token-0123456789-abcdefghij"


def test_set_rejects_blank_token(tmp_path):
    root = make_root(tmp_path)
    (root / "backend" / ".env").write_text("", encoding="utf-8")
    (root / "web-client" / ".env").write_text("", encoding="utf-8")
    code = edit_auth._cmd_set(_args(root, token="   "))
    assert code == 1


def test_get_masks_by_default_and_shows_with_flag(tmp_path, capsys):
    root = make_root(tmp_path)
    (root / "backend" / ".env").write_text("AUTH_TOKEN=abcdefgh1234\n", encoding="utf-8")

    edit_auth._cmd_get(_args(root, show=False))
    masked = capsys.readouterr().out.strip()
    assert masked != "abcdefgh1234"
    assert masked.endswith("1234")

    edit_auth._cmd_get(_args(root, show=True))
    shown = capsys.readouterr().out.strip()
    assert shown == "abcdefgh1234"


def test_get_json_mode(tmp_path, capsys):
    import json

    root = make_root(tmp_path)
    (root / "backend" / ".env").write_text("AUTH_TOKEN=abcdefgh1234\n", encoding="utf-8")
    edit_auth._cmd_get(_args(root, json=True, show=True))
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": True, "token": "abcdefgh1234"}


def test_set_rejects_token_shorter_than_minimum(tmp_path):
    root = make_root(tmp_path)
    (root / "backend" / ".env").write_text("", encoding="utf-8")
    (root / "web-client" / ".env").write_text("", encoding="utf-8")

    assert edit_auth._cmd_set(_args(root, token="a" * 31)) == 1
    assert "AUTH_TOKEN" not in envio.read_env_file(root / "backend" / ".env")

    assert edit_auth._cmd_set(_args(root, token="a" * 32)) == 0
    assert envio.read_env_file(root / "backend" / ".env")["AUTH_TOKEN"] == "a" * 32


_TOKEN = "t" * 40


class _Tty:
    def isatty(self):
        return True


def _envs(root):
    (root / "backend" / ".env").write_text("A=1\n", encoding="utf-8")
    (root / "web-client" / ".env").write_text("B=2\n", encoding="utf-8")


def test_set_stdin_reads_one_line(tmp_path, monkeypatch, capsys):
    import io

    root = make_root(tmp_path)
    _envs(root)
    monkeypatch.setattr(edit_auth.sys, "stdin", io.StringIO(_TOKEN + "\nrest\n"))
    assert edit_auth._cmd_set(_args(root, stdin=True)) == 0
    assert envio.read_env_file(root / "backend" / ".env")["AUTH_TOKEN"] == _TOKEN
    assert envio.read_env_file(root / "web-client" / ".env")["AUTH_TOKEN"] == _TOKEN
    assert capsys.readouterr().err == ""


def test_set_prompts_with_getpass_on_tty(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    _envs(root)
    monkeypatch.setattr(edit_auth.sys, "stdin", _Tty())
    monkeypatch.setattr(edit_auth.getpass, "getpass", lambda prompt="": _TOKEN)
    assert edit_auth._cmd_set(_args(root)) == 0
    assert envio.read_env_file(root / "backend" / ".env")["AUTH_TOKEN"] == _TOKEN


def test_set_without_source_and_no_tty_errors(tmp_path, monkeypatch):
    import io

    root = make_root(tmp_path)
    _envs(root)
    monkeypatch.setattr(edit_auth.sys, "stdin", io.StringIO(""))
    assert edit_auth._cmd_set(_args(root)) == 1
    assert "AUTH_TOKEN" not in envio.read_env_file(root / "backend" / ".env")


def test_set_positional_works_but_warns(tmp_path, capsys):
    root = make_root(tmp_path)
    _envs(root)
    assert edit_auth._cmd_set(_args(root, token=_TOKEN)) == 0
    assert envio.read_env_file(root / "backend" / ".env")["AUTH_TOKEN"] == _TOKEN
    assert i18n.t("secret.argv_warning", alternative="--stdin") in capsys.readouterr().err


def test_set_stdin_short_token_rejected(tmp_path, monkeypatch):
    import io

    root = make_root(tmp_path)
    _envs(root)
    monkeypatch.setattr(edit_auth.sys, "stdin", io.StringIO("short\n"))
    assert edit_auth._cmd_set(_args(root, stdin=True)) == 1
    assert "AUTH_TOKEN" not in envio.read_env_file(root / "backend" / ".env")


def test_set_positional_and_stdin_conflict(tmp_path, monkeypatch, capsys):
    root = make_root(tmp_path)
    _envs(root)
    monkeypatch.setattr(edit_auth.sys, "stdin", io.StringIO(_TOKEN + "\n"))
    assert edit_auth._cmd_set(_args(root, token=_TOKEN, stdin=True)) == 1
    captured = capsys.readouterr()
    assert i18n.t("auth.token_conflict") in captured.err
    # no write, and no argv warning for a rejected invocation
    assert i18n.t("secret.argv_warning", alternative="--stdin") not in captured.err
    assert "AUTH_TOKEN" not in envio.read_env_file(root / "backend" / ".env")
