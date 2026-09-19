from installer import wizard
from rona_cli import envio

# ---- _prompt_fields --------------------------------------------------


def test_prompt_fields_blank_keeps_current(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    result = wizard._prompt_fields({"name": "Ad"}, set(), {"name": "existing"})
    assert result == {}


def test_prompt_fields_entering_value_overrides(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "new-value")
    result = wizard._prompt_fields({"name": "Ad"}, set(), {"name": "existing"})
    assert result == {"name": "new-value"}


def test_prompt_fields_skip_word_aborts_whole_block(monkeypatch):
    responses = iter(["typed-name", "s"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))
    result = wizard._prompt_fields({"name": "Ad", "url": "URL"}, set(), {})
    assert result is None


def test_prompt_fields_uses_getpass_for_secret_fields(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "public-value")
    monkeypatch.setattr(wizard.getpass, "getpass", lambda prompt="": "secret-value")
    result = wizard._prompt_fields({"name": "Ad", "key": "Key"}, {"key"}, {})
    assert result == {"name": "public-value", "key": "secret-value"}


# ---- _ask_choice -------------------------------------------------------


def test_ask_choice_returns_selected_index(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "2")
    assert wizard._ask_choice(["a", "b", "c"]) == 1


def test_ask_choice_eof_returns_last_safe_option(monkeypatch):
    def _raise(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise)
    assert wizard._ask_choice(["a", "b", "c"]) == 2


def test_ask_choice_reprompts_on_invalid_input(monkeypatch):
    responses = iter(["bogus", "0", "5", "2"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))
    assert wizard._ask_choice(["a", "b"]) == 1


# ---- _run_block ----------------------------------------------------------


def test_run_block_test_success_returns_candidate(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "value")
    result = wizard._run_block(
        "Title", {"name": "Ad"}, set(), {}, required=True, test_fn=lambda c: (True, "ok")
    )
    assert result == {"name": "value"}


def test_run_block_skip_word_returns_none(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "s")
    result = wizard._run_block(
        "Title", {"name": "Ad"}, set(), {}, required=True, test_fn=lambda c: (True, "ok")
    )
    assert result is None


def test_run_block_nothing_entered_and_no_current_skips(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    result = wizard._run_block(
        "Title", {"name": "Ad"}, set(), {}, required=True, test_fn=lambda c: (True, "ok")
    )
    assert result is None


def test_run_block_failure_then_retry_then_success(monkeypatch):
    responses = iter(["bad-value", "1", "good-value"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))
    calls = []

    def fake_test(candidate):
        calls.append(candidate["name"])
        return (candidate["name"] == "good-value", "detail")

    result = wizard._run_block(
        "Title", {"name": "Ad"}, set(), {}, required=True, test_fn=fake_test
    )
    assert result == {"name": "good-value"}
    assert calls == ["bad-value", "good-value"]


def test_run_block_failure_then_save_anyway(monkeypatch):
    responses = iter(["bad-value", "2"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))
    result = wizard._run_block(
        "Title", {"name": "Ad"}, set(), {}, required=False, test_fn=lambda c: (False, "nope")
    )
    assert result == {"name": "bad-value"}


def test_run_block_failure_then_skip(monkeypatch):
    responses = iter(["bad-value", "3"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))
    result = wizard._run_block(
        "Title", {"name": "Ad"}, set(), {}, required=False, test_fn=lambda c: (False, "nope")
    )
    assert result is None


# ---- _write_block ----------------------------------------------------------


def test_write_block_writes_plain_fields(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")
    wizard._write_block(
        env_path,
        {"name": "FLASH_MODEL", "url": "FLASH_MODEL_URL"},
        {"name": "m", "url": "http://x"},
    )
    values = envio.read_env_file(env_path)
    assert values["FLASH_MODEL"] == "m"
    assert values["FLASH_MODEL_URL"] == "http://x"


def test_write_block_encodes_headers_as_json(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")
    wizard._write_block(
        env_path, {"headers": "FLASH_MODEL_HEADERS"}, {"headers": '{"x-foo": "bar"}'}
    )
    values = envio.read_env_file(env_path)
    assert values["FLASH_MODEL_HEADERS"] == '{"x-foo": "bar"}'


def test_write_block_missing_field_writes_empty_string(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")
    wizard._write_block(env_path, {"name": "FLASH_MODEL"}, {})
    values = envio.read_env_file(env_path)
    assert values["FLASH_MODEL"] == ""


# ---- run() ----------------------------------------------------------------


def test_run_backend_not_in_scope_does_nothing(tmp_path):
    root = tmp_path / "root"
    # No backend/ dir at all -- if run() tried to do anything beyond the
    # early return, this would raise (no .env to read).
    wizard.run(root, backend_in_scope=False)


def test_run_full_skip_flow_leaves_env_empty(tmp_path, monkeypatch, capsys):
    root = tmp_path / "root"
    (root / "backend").mkdir(parents=True)
    (root / "backend" / ".env").write_text("", encoding="utf-8")

    # Flash's and pro's first field ("name") is read via input(); pro's
    # "same as flash?" confirm is short-circuited (flash_result is None)
    # so it goes straight to its own block. Embedding's first field
    # ("key") is secret, read via getpass() instead.
    responses = iter(["s", "s"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))
    monkeypatch.setattr(wizard.getpass, "getpass", lambda prompt="": "s")

    wizard.run(root, backend_in_scope=True)

    assert envio.read_env_file(root / "backend" / ".env") == {}
    out = capsys.readouterr().out
    assert "Flash atlandı" in out


def test_run_full_success_flow_writes_all_three(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "backend").mkdir(parents=True)
    (root / "backend" / ".env").write_text("", encoding="utf-8")

    # Flash: name, url, headers(blank) via input(); key via getpass().
    # Pro: "use same as flash?" -> yes, via input() (no further prompts).
    # Embedding: key via getpass(); name via input().
    text_inputs = iter(["flash-model", "http://flash", "", "e", "embed-model"])
    secret_inputs = iter(["flash-key", "embed-key"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(text_inputs))
    monkeypatch.setattr(wizard.getpass, "getpass", lambda prompt="": next(secret_inputs))
    monkeypatch.setattr(wizard.providers, "test_chat_model", lambda *a, **k: (True, "ok"))
    monkeypatch.setattr(wizard.providers, "test_embedding", lambda *a, **k: (True, "ok"))

    wizard.run(root, backend_in_scope=True)

    values = envio.read_env_file(root / "backend" / ".env")
    assert values["FLASH_MODEL"] == "flash-model"
    assert values["FLASH_MODEL_URL"] == "http://flash"
    assert values["FLASH_MODEL_API"] == "flash-key"
    assert values["PRO_MODEL"] == "flash-model"
    assert values["PRO_MODEL_API"] == "flash-key"
    assert values["GOOGLE_API_KEY"] == "embed-key"
    assert values["EMBEDDING_MODEL_NAME"] == "embed-model"


def test_run_pro_declines_same_as_flash_and_skips(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "backend").mkdir(parents=True)
    (root / "backend" / ".env").write_text("", encoding="utf-8")

    # Flash succeeds (name, url, headers via input(); key via getpass()).
    # Pro declines "same as flash?" (input()) then skips its own block on
    # its first field, "name" (input()). Embedding skips on its first
    # field, "key" -- secret, via getpass().
    text_inputs = iter(["flash-model", "http://flash", "", "h", "s"])
    secret_inputs = iter(["flash-key", "s"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(text_inputs))
    monkeypatch.setattr(wizard.getpass, "getpass", lambda prompt="": next(secret_inputs))
    monkeypatch.setattr(wizard.providers, "test_chat_model", lambda *a, **k: (True, "ok"))

    wizard.run(root, backend_in_scope=True)

    values = envio.read_env_file(root / "backend" / ".env")
    assert values["FLASH_MODEL"] == "flash-model"
    assert "PRO_MODEL" not in values
    assert "GOOGLE_API_KEY" not in values
