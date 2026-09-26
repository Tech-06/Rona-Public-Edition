"""Shared fixtures for the backend test suite."""

import pytest


@pytest.fixture(autouse=True)
def _isolated_prompt_overrides(tmp_path, monkeypatch):
    """Every test gets its own empty prompt-override directory.

    Without this, a developer's real ``backend/prompts/custom/``
    overrides (or files left behind by a previous test run) would leak
    into the suite, and prompt-store tests would write into the real,
    git-ignored override directory instead of a throwaway one.

    ``app.prompt_store`` is imported here, inside the fixture body,
    rather than at module level, so collecting this conftest doesn't
    force that module (and everything it pulls in) to load for test
    files that have nothing to do with prompts.
    """
    from app import prompt_store

    monkeypatch.setattr(prompt_store, "CUSTOM_DIR", tmp_path / "prompts_custom")
    yield
