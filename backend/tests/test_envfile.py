import os

import pytest

from toolbox.envfile import (
    EnvValueError,
    read_env_file,
    remove_env_keys,
    write_env_updates,
)

POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")


@pytest.mark.parametrize("bad", ["a\rb", "a\nb", "a\r\nb", "a\x00b"])
def test_value_with_line_break_or_nul_rejected_and_file_untouched(tmp_path, bad):
    env = tmp_path / ".env"
    env.write_text("A=1\n", encoding="utf-8")

    with pytest.raises(EnvValueError) as info:
        write_env_updates(env, {"B": "ok", "A": bad})

    assert "A" in str(info.value)
    assert env.read_text(encoding="utf-8") == "A=1\n"  # no partial write
    assert not env.with_suffix(".bak").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == [".env"]


@pytest.mark.parametrize("bad_key", ["1A", "A-B", "A B", "", "A=B"])
def test_invalid_keys_rejected(tmp_path, bad_key):
    env = tmp_path / ".env"
    env.write_text("A=1\n", encoding="utf-8")
    with pytest.raises(EnvValueError):
        write_env_updates(env, {bad_key: "v"})
    with pytest.raises(EnvValueError):
        remove_env_keys(env, [bad_key])
    assert env.read_text(encoding="utf-8") == "A=1\n"


def test_valid_update_works_and_leaves_no_temp_files(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\n", encoding="utf-8")

    write_env_updates(env, {"A": "2", "_B1": "x y"})

    assert read_env_file(env) == {"A": "2", "_B1": "x y"}
    assert sorted(p.name for p in tmp_path.iterdir()) == [".env", ".env.bak"]


def test_failed_write_cleans_up_temp_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("A=1\n", encoding="utf-8")

    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        write_env_updates(env, {"A": "2"})

    assert env.read_text(encoding="utf-8") == "A=1\n"
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


@POSIX_ONLY
def test_env_and_backup_are_owner_only(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\n", encoding="utf-8")
    env.chmod(0o644)
    previous = os.umask(0o022)
    try:
        write_env_updates(env, {"A": "2"})
    finally:
        os.umask(previous)

    assert (env.stat().st_mode & 0o777) == 0o600
    assert (env.with_suffix(".bak").stat().st_mode & 0o777) == 0o600
