"""`rona web password` and the shared password-hash format.

The fixed vector below is asserted verbatim in web-client/tests/test_auth.py
too: the two implementations (rona_cli.webauth and webui.auth) must never drift.
"""

import io
import sys
from types import SimpleNamespace

import pytest

from rona_cli import envio, webauth
from rona_cli.commands import web

from .helpers import make_root

VECTOR_PASSWORD = "correct horse battery staple"
VECTOR_SALT = bytes(range(16))
VECTOR_HASH = "scrypt$32768$8$1$AAECAwQFBgcICQoLDA0ODw$eo40JB24mNWRdcaWU4xBdGepdf_laQaEJfFhiNMVnFg"


class _Stdin(io.StringIO):
    def __init__(self, text: str, tty: bool):
        super().__init__(text)
        self._tty = tty

    def isatty(self):
        return self._tty


def _args(root, **overrides):
    return SimpleNamespace(root=str(root), json=False, stdin=True, **overrides)


@pytest.fixture
def root(tmp_path):
    root = make_root(tmp_path)
    (root / "web-client" / ".env").write_text("AUTH_TOKEN=x\n", encoding="utf-8")
    return root


def _env(root):
    return envio.read_env_file(root / "web-client" / ".env")


def test_fixed_vector():
    assert webauth.hash_password(VECTOR_PASSWORD, salt=VECTOR_SALT) == VECTOR_HASH
    assert webauth.verify_password(VECTOR_PASSWORD, VECTOR_HASH)
    assert not webauth.verify_password("something else", VECTOR_HASH)


@pytest.mark.parametrize("stored", ["", "garbage", "scrypt$1$2$3", "scrypt$x$8$1$AAEC$AAEC"])
def test_malformed_hash_is_false(stored):
    assert webauth.verify_password("whatever", stored) is False


def test_password_stdin_writes_verifiable_hash_and_secret(root, monkeypatch):
    monkeypatch.setattr(sys, "stdin", _Stdin("a long enough password\n", tty=False))

    assert web._cmd_password(_args(root)) == 0

    env = _env(root)
    assert env["AUTH_TOKEN"] == "x"
    assert webauth.verify_password("a long enough password", env["WEB_PASSWORD_HASH"])
    assert len(env["WEB_SESSION_SECRET"]) >= 32


def test_password_rotates_session_secret(root, monkeypatch):
    secrets_seen = []
    for text in ("first long password\n", "second long password\n"):
        monkeypatch.setattr(sys, "stdin", _Stdin(text, tty=False))
        assert web._cmd_password(_args(root)) == 0
        secrets_seen.append(_env(root)["WEB_SESSION_SECRET"])
    assert secrets_seen[0] != secrets_seen[1]


def test_short_password_is_rejected(root, monkeypatch):
    monkeypatch.setattr(sys, "stdin", _Stdin("abc\n", tty=False))

    assert web._cmd_password(_args(root)) == 1
    assert "WEB_PASSWORD_HASH" not in _env(root)


def test_tty_mismatch_is_rejected(root, monkeypatch):
    monkeypatch.setattr(sys, "stdin", _Stdin("", tty=True))
    answers = iter(["first long password", "different long password"])
    monkeypatch.setattr(web.getpass, "getpass", lambda prompt="": next(answers))

    code = web._cmd_password(SimpleNamespace(root=str(root), json=False, stdin=False))

    assert code == 1
    assert "WEB_PASSWORD_HASH" not in _env(root)


def test_tty_match_is_accepted(root, monkeypatch):
    monkeypatch.setattr(sys, "stdin", _Stdin("", tty=True))
    monkeypatch.setattr(web.getpass, "getpass", lambda prompt="": "a long enough password")

    code = web._cmd_password(SimpleNamespace(root=str(root), json=False, stdin=False))

    assert code == 0
    assert webauth.verify_password("a long enough password", _env(root)["WEB_PASSWORD_HASH"])


def test_non_tty_without_stdin_flag_fails(root, monkeypatch):
    monkeypatch.setattr(sys, "stdin", _Stdin("a long enough password\n", tty=False))

    code = web._cmd_password(SimpleNamespace(root=str(root), json=False, stdin=False))

    assert code == 1
    assert "WEB_PASSWORD_HASH" not in _env(root)


def test_fails_cleanly_when_web_client_not_installed(tmp_path, monkeypatch, capsys):
    root = make_root(tmp_path)  # web-client/ exists but has no .env
    monkeypatch.setattr(sys, "stdin", _Stdin("a long enough password\n", tty=False))

    assert web._cmd_password(_args(root)) == 1
    assert not (root / "web-client" / ".env").exists()


def test_json_output(root, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", _Stdin("a long enough password\n", tty=False))
    args = SimpleNamespace(root=str(root), json=True, stdin=True)

    assert web._cmd_password(args) == 0
    assert '"ok": true' in capsys.readouterr().out


def test_password_is_never_a_positional_argument():
    from rona_cli.cli import build_parser

    args = build_parser().parse_args(["web", "password", "--stdin"])
    assert args.web_command == "password" and args.stdin is True
    with pytest.raises(SystemExit):
        build_parser().parse_args(["web", "password", "hunter2hunter2"])
