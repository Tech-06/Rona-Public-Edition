import os

import pytest

from rona_cli.commands.edit import env as edit_env


@pytest.fixture(autouse=True)
def _no_editor_env(monkeypatch):
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)


def test_editor_command_splits_flags(monkeypatch):
    monkeypatch.setenv("EDITOR", "code --wait")
    assert edit_env._editor_command() == ["code", "--wait"]


def test_editor_command_keeps_existing_path_with_spaces_whole(monkeypatch, tmp_path):
    editor = tmp_path / "My Editor" / "edit.exe"
    editor.parent.mkdir()
    editor.write_text("")
    monkeypatch.setenv("EDITOR", str(editor))
    assert edit_env._editor_command() == [str(editor)]


@pytest.mark.skipif(os.name != "nt", reason="Windows path handling")
def test_editor_command_keeps_windows_backslashes_with_flags(monkeypatch):
    monkeypatch.setenv("EDITOR", r'"C:\Program Files\Editor\edit.exe" --wait')
    assert edit_env._editor_command() == [r"C:\Program Files\Editor\edit.exe", "--wait"]


def test_visual_takes_precedence(monkeypatch):
    monkeypatch.setenv("VISUAL", "vim")
    monkeypatch.setenv("EDITOR", "nano")
    assert edit_env._editor_command() == ["vim"]
