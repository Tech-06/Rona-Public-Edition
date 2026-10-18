import sys

import pytest
from rona_cli import envio, webauth

from installer.steps import web as web_step

PASSWORD = "a long enough password"


@pytest.fixture
def env_path(tmp_path):
    path = tmp_path / ".env"
    path.write_text("AUTH_TOKEN=x\n", encoding="utf-8")
    return path


def _tty(monkeypatch, answers):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    queue = iter(answers)
    monkeypatch.setattr(web_step.getpass, "getpass", lambda prompt="": next(queue))


def test_prompts_and_writes_hash_and_secret(env_path, monkeypatch):
    _tty(monkeypatch, [PASSWORD, PASSWORD])

    web_step._ensure_panel_password(env_path)

    env = envio.read_env_file(env_path)
    assert webauth.verify_password(PASSWORD, env["WEB_PASSWORD_HASH"])
    assert len(env["WEB_SESSION_SECRET"]) >= 32
    assert env["AUTH_TOKEN"] == "x"


def test_empty_input_skips_with_hint(env_path, monkeypatch, capsys):
    _tty(monkeypatch, [""])

    web_step._ensure_panel_password(env_path)

    assert "WEB_PASSWORD_HASH" not in envio.read_env_file(env_path)
    assert "rona web password" in capsys.readouterr().out


def test_mismatch_and_short_are_reprompted(env_path, monkeypatch):
    _tty(monkeypatch, ["first long password", "other long password", "abc", "abc", PASSWORD, PASSWORD])

    web_step._ensure_panel_password(env_path)

    assert webauth.verify_password(PASSWORD, envio.read_env_file(env_path)["WEB_PASSWORD_HASH"])


def test_gives_up_after_three_attempts(env_path, monkeypatch):
    _tty(monkeypatch, ["aaaaaaaaaaaa", "bbbbbbbbbbbb"] * 3)

    web_step._ensure_panel_password(env_path)

    assert "WEB_PASSWORD_HASH" not in envio.read_env_file(env_path)


def test_non_interactive_skips_with_hint(env_path, monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(
        web_step.getpass, "getpass", lambda prompt="": pytest.fail("must not prompt")
    )

    web_step._ensure_panel_password(env_path)

    assert "WEB_PASSWORD_HASH" not in envio.read_env_file(env_path)
    assert "rona web password" in capsys.readouterr().out


def test_existing_hash_is_kept(env_path, monkeypatch):
    existing = webauth.hash_password("previous password!")
    envio.write_env_updates(env_path, {"WEB_PASSWORD_HASH": existing})
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(
        web_step.getpass, "getpass", lambda prompt="": pytest.fail("must not prompt")
    )

    web_step._ensure_panel_password(env_path)

    assert envio.read_env_file(env_path)["WEB_PASSWORD_HASH"] == existing
