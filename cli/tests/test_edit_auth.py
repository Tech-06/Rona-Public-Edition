from types import SimpleNamespace

from rona_cli import envio
from rona_cli.commands.edit import auth as edit_auth

from .helpers import make_root


def _args(root, **overrides):
    defaults = {"root": str(root), "json": False, "show": False, "yes": False, "token": None}
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

    code = edit_auth._cmd_set(_args(root, token="my-custom-token"))
    assert code == 0
    assert envio.read_env_file(root / "backend" / ".env")["AUTH_TOKEN"] == "my-custom-token"
    assert envio.read_env_file(root / "web-client" / ".env")["AUTH_TOKEN"] == "my-custom-token"


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
