"""Shared fixtures for the backend test suite."""

import os
import shutil
import sys

import pytest

# app.config reads backend/.env at import; a developer's local .env may hold a
# short placeholder token that the 32-char minimum now rejects. Environment
# variables win over .env, so pin a valid one before anything imports app.
os.environ["AUTH_TOKEN"] = "pytest-auth-token-0123456789abcdef"


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


@pytest.fixture(scope="session")
def _template_db(tmp_path_factory):
    """One freshly created rona.db, copied into each test (cheaper than
    running every migration per test)."""
    import create_db
    from toolbox import db as toolbox_db

    path = tmp_path_factory.mktemp("template_db") / "rona.db"
    real_toolbox, real_create = toolbox_db.DB_PATH, create_db.DB_PATH
    toolbox_db.DB_PATH = create_db.DB_PATH = path
    try:
        create_db.create_database()
    finally:
        toolbox_db.DB_PATH, create_db.DB_PATH = real_toolbox, real_create
    return path


@pytest.fixture(autouse=True)
def _isolated_database(_template_db, tmp_path_factory, monkeypatch):
    """Every test gets its own copy of a fresh database.

    Code paths such as the agent node's unreported-run notifications open
    ``toolbox.db.DB_PATH`` directly; without this, tests that drive them
    (and don't patch the path themselves) read and write the developer's
    real ``backend/rona.db``. Tests that need a specific schema still
    monkeypatch DB_PATH themselves, which overrides this.
    """
    import create_db
    from toolbox import db as toolbox_db

    # Outside the test's own tmp_path, which some tests list or assert empty.
    path = tmp_path_factory.mktemp("isolated_db") / "rona.db"
    shutil.copyfile(_template_db, path)
    monkeypatch.setattr(toolbox_db, "DB_PATH", path)
    monkeypatch.setattr(create_db, "DB_PATH", path)
    dashboard = sys.modules.get("app.dashboard")
    if dashboard is not None and hasattr(dashboard, "DB_PATH"):
        monkeypatch.setattr(dashboard, "DB_PATH", path)
    yield
