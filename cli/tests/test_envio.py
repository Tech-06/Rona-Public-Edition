from rona_cli import envio


def test_read_env_file_missing_returns_empty(tmp_path):
    assert envio.read_env_file(tmp_path / ".env") == {}


def test_read_env_file_parses_pairs_and_skips_comments(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# a comment\nAUTH_TOKEN=abc123\n\nFLASH_MODEL=gpt\nMALFORMED_LINE\n",
        encoding="utf-8",
    )
    values = envio.read_env_file(env_path)
    assert values == {"AUTH_TOKEN": "abc123", "FLASH_MODEL": "gpt"}


def test_write_env_updates_replaces_existing_key_in_place(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("A=1\nB=2\nC=3\n", encoding="utf-8")
    envio.write_env_updates(env_path, {"B": "20"})
    assert env_path.read_text(encoding="utf-8").splitlines() == ["A=1", "B=20", "C=3"]


def test_write_env_updates_appends_new_keys(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("A=1\n", encoding="utf-8")
    envio.write_env_updates(env_path, {"NEW_KEY": "value"})
    lines = env_path.read_text(encoding="utf-8").splitlines()
    assert lines == ["A=1", "NEW_KEY=value"]


def test_write_env_updates_creates_file_when_missing(tmp_path):
    env_path = tmp_path / ".env"
    envio.write_env_updates(env_path, {"A": "1"})
    assert env_path.read_text(encoding="utf-8") == "A=1\n"


def test_write_env_updates_leaves_comments_and_unrelated_lines_untouched(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("# header comment\nA=1\n\nB=2\n", encoding="utf-8")
    envio.write_env_updates(env_path, {"A": "10"})
    lines = env_path.read_text(encoding="utf-8").splitlines()
    assert lines == ["# header comment", "A=10", "", "B=2"]


def test_write_env_updates_backs_up_previous_content(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("A=1\n", encoding="utf-8")
    envio.write_env_updates(env_path, {"A": "2"})
    backup_path = env_path.with_suffix(".bak")
    assert backup_path.read_text(encoding="utf-8") == "A=1\n"


def test_remove_env_keys_deletes_matching_lines(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("A=1\nB=2\nC=3\n", encoding="utf-8")
    envio.remove_env_keys(env_path, ["B"])
    assert env_path.read_text(encoding="utf-8").splitlines() == ["A=1", "C=3"]


def test_remove_env_keys_noop_when_key_absent(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("A=1\n", encoding="utf-8")
    envio.remove_env_keys(env_path, ["MISSING"])
    assert env_path.read_text(encoding="utf-8") == "A=1\n"


def test_remove_env_keys_noop_when_file_missing(tmp_path):
    env_path = tmp_path / ".env"
    envio.remove_env_keys(env_path, ["A"])
    assert not env_path.exists()


def test_write_then_read_round_trip(tmp_path):
    env_path = tmp_path / ".env"
    envio.write_env_updates(env_path, {"AUTH_TOKEN": "xyz", "PORT": "8000"})
    values = envio.read_env_file(env_path)
    assert values["AUTH_TOKEN"] == "xyz"
    assert values["PORT"] == "8000"
