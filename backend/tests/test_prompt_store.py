"""Tests for app/prompt_store.py: default-vs-override resolution,
validation, optimistic-concurrency writes and reset. The autouse fixture
in conftest.py points prompt_store.CUSTOM_DIR at a fresh tmp_path for
every test, so these never touch the real, git-ignored override
directory.
"""

import pytest

import app.prompts as prompts_module
from app import prompt_store


def test_default_used_without_override():
    result = prompt_store.read("persona")
    on_disk = (prompt_store.PROMPTS_DIR / "persona.md").read_text(encoding="utf-8")
    assert result["content"] == on_disk
    assert result["default_content"] == on_disk
    assert result["customized"] is False
    assert result["default_changed"] is None


def test_override_wins_and_load_prompts_uses_it():
    current = prompt_store.read("persona")
    new_content = (
        "# Custom Persona\n\nYou are Test-Rona. {{PRIMARY_LANGUAGE_RULE}}\n"
    )
    prompt_store.write("persona", new_content, current["version"])

    assert prompt_store.load_text("persona") == new_content
    assert "Test-Rona" in prompt_store.load_rendered("persona")

    messages = prompts_module.load_prompts()
    combined = "\n".join(message["content"] for message in messages)
    assert "Test-Rona" in combined
    # the placeholder token itself must have been substituted away
    assert "{{PRIMARY_LANGUAGE_RULE}}" not in combined


def test_missing_required_placeholder_rejected():
    current = prompt_store.read("persona")
    with pytest.raises(prompt_store.PromptValidationError) as excinfo:
        prompt_store.write("persona", "no placeholder here\n", current["version"])
    assert excinfo.value.messages


def test_empty_worker_prompt_rejected():
    current = prompt_store.read("subagent_worker")
    with pytest.raises(prompt_store.PromptValidationError):
        prompt_store.write("subagent_worker", "   \n\n  ", current["version"])


def test_oversize_rejected():
    current = prompt_store.read("user")
    too_big = "x" * (prompt_store.MAX_PROMPT_BYTES + 1)
    with pytest.raises(prompt_store.PromptValidationError) as excinfo:
        prompt_store.write("user", too_big, current["version"])
    assert excinfo.value.messages


def test_stale_base_version_conflicts():
    current = prompt_store.read("user")
    prompt_store.write("user", "first edit\n", current["version"])
    with pytest.raises(prompt_store.PromptConflict) as excinfo:
        prompt_store.write("user", "second edit\n", current["version"])
    latest = prompt_store.read("user")
    assert excinfo.value.current_version == latest["version"]


def test_reset_removes_override_and_meta():
    current = prompt_store.read("user")
    prompt_store.write("user", "custom user content\n", current["version"])
    assert prompt_store.summary("user")["customized"] is True

    result = prompt_store.reset("user")
    assert result["customized"] is False
    assert result["content"] == result["default_content"]
    assert not prompt_store.override_path("user").exists()
    assert "user" not in prompt_store._read_meta()


def test_default_changed_flag():
    current = prompt_store.read("user")
    prompt_store.write("user", "custom user content\n", current["version"])
    assert prompt_store.summary("user")["default_changed"] is False

    # Simulate the tracked default having changed since the override was
    # made, without touching the real backend/prompts/user.md file: tamper
    # the stored "as of" hash directly.
    meta = prompt_store._read_meta()
    meta["user"]["default_version"] = "0" * 16
    prompt_store._write_meta(meta)

    assert prompt_store.summary("user")["default_changed"] is True


def test_worker_loaders_use_override():
    current = prompt_store.read("trigger_worker")
    new_content = (
        '{"outcome": "done"} or {"outcome": "condition_not_met"} -- custom copy\n'
    )
    prompt_store.write("trigger_worker", new_content, current["version"])
    assert prompt_store.load_worker_prompt("trigger_worker") == new_content.strip()


def test_contract_marker_warning():
    current = prompt_store.read("trigger_worker")
    content_missing_marker = "outcome only, no condition marker here\n"
    result = prompt_store.write("trigger_worker", content_missing_marker, current["version"])
    assert result["warnings"]
    assert any("condition_not_met" in warning for warning in result["warnings"])


def test_crlf_normalized():
    current = prompt_store.read("user")
    result = prompt_store.write("user", "line one\r\nline two\r\n", current["version"])
    assert "\r" not in result["content"]
    assert result["content"] == "line one\nline two\n"
    on_disk = prompt_store.override_path("user").read_text(encoding="utf-8")
    assert "\r" not in on_disk


def test_no_temp_files_left():
    current = prompt_store.read("user")
    prompt_store.write("user", "content one\n", current["version"])
    current = prompt_store.read("user")
    prompt_store.write("user", "content two\n", current["version"])
    prompt_store.reset("user")
    leftovers = list(prompt_store.CUSTOM_DIR.glob(".tmp-*"))
    assert leftovers == []


def test_unknown_id():
    with pytest.raises(prompt_store.PromptNotFound):
        prompt_store.spec("nope")
    with pytest.raises(prompt_store.PromptNotFound):
        prompt_store.read("nope")
    with pytest.raises(prompt_store.PromptNotFound):
        prompt_store.write("nope", "x", "v")
    with pytest.raises(prompt_store.PromptNotFound):
        prompt_store.reset("nope")
