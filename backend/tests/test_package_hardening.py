"""Hardening of custom packages: pip requirement validation, package-relative
tool modules, and opt-in purge on uninstall (.env keys + schema tables)."""

import json
import sqlite3
import subprocess

import pytest
from test_manager import _simple_tool, catalog, manager_env  # noqa: F401

import toolbox
from toolbox import db, manager, packages
from toolbox.manager import ManagerError
from toolbox.packages import PackageLoadError, PackageManifest

# ---------------------------------------------------------------------------
# python_requirements
# ---------------------------------------------------------------------------

BAD_REQUIREMENTS = [
    "--index-url=https://evil.example/simple",
    "--extra-index-url https://evil.example",
    "-e .",
    "-r other.txt",
    "git+https://github.com/evil/pkg.git",
    "https://evil.example/pkg.whl",
    "pkg @ https://evil.example/pkg.whl",
    "pkg@https://evil.example/pkg.whl",
    "./local_dir",
    "../sibling",
    "/abs/path/pkg",
    "~/pkg",
    "C:\\pkgs\\x",
    "sub/dir",
    "",
    "not a requirement!!",
]


@pytest.mark.parametrize("bad", BAD_REQUIREMENTS)
def test_pip_install_rejects_bad_requirement_before_running_pip(bad, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("pip must not run")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(ManagerError, match="invalid python requirement"):
        manager._pip_install(["requests>=2.31", bad])


@pytest.mark.parametrize("bad", BAD_REQUIREMENTS)
def test_manifest_rejects_bad_requirement(bad):
    with pytest.raises(Exception, match="python requirement"):
        PackageManifest.model_validate(
            {"id": "p", "version": "1", "name": "p", "python_requirements": [bad]}
        )


def test_pip_install_accepts_normal_requirements(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="Successfully installed x", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    reqs = ["requests>=2.31", "google-api-python-client[extra]>=2,<3", 'pywin32; sys_platform == "win32"']
    assert manager._pip_install(reqs) is True
    # Everything after "--" is data, never an option.
    assert seen["argv"][-len(reqs) - 1 :] == ["--", *reqs]


def test_install_with_malicious_requirement_fails_and_leaves_nothing(
    catalog, manager_env, monkeypatch  # noqa: F811
):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("pip ran"))
    catalog(
        "evil_req",
        manifest_extra={"python_requirements": ["--index-url=https://evil.example"]},
    )
    manager_env.append("evil_req")
    with pytest.raises(Exception):  # noqa: B017 -- load/validation error, either type
        manager.install("evil_req", source=catalog.source_spec)
    assert not manager.is_installed("evil_req")


# ---------------------------------------------------------------------------
# tools.json modules
# ---------------------------------------------------------------------------


def _manifest(pid="modpkg"):
    return PackageManifest.model_validate({"id": pid, "version": "1", "name": pid})


def _write_tools(tmp_path, module):
    pkg = tmp_path / "modpkg"
    pkg.mkdir(exist_ok=True)
    (pkg / "tools.json").write_text(
        json.dumps({"tools": [{**_simple_tool("modtool"), "module": module}]}),
        encoding="utf-8",
    )
    return pkg


@pytest.mark.parametrize("module", ["os", "toolbox.tools.mem_tool", "", "modtool"])
def test_custom_package_absolute_module_rejected(tmp_path, module):
    pkg = _write_tools(tmp_path, module)
    with pytest.raises(PackageLoadError, match="relative to the package"):
        packages.load_tools_raw(pkg, _manifest())


def test_custom_package_missing_module_rejected(tmp_path):
    pkg = tmp_path / "modpkg"
    pkg.mkdir()
    tool = _simple_tool("modtool")
    del tool["module"]
    (pkg / "tools.json").write_text(json.dumps({"tools": [tool]}), encoding="utf-8")
    with pytest.raises(PackageLoadError):
        packages.load_tools_raw(pkg, _manifest())


def test_custom_package_relative_module_resolved(tmp_path):
    pkg = _write_tools(tmp_path, ".modtool")
    (tool,) = packages.load_tools_raw(pkg, _manifest())
    assert tool["module"] == "toolbox.custom.modpkg.modtool"


def test_install_rejects_absolute_module_package(catalog, manager_env):  # noqa: F811
    catalog(
        "abs_mod",
        tools=[{**_simple_tool("abs_mod_tool"), "module": "os"}],
        module_source="",
    )
    manager_env.append("abs_mod")
    with pytest.raises(Exception):  # noqa: B017
        manager.install("abs_mod", source=catalog.source_spec)
    assert not manager.is_installed("abs_mod")
    assert not toolbox.has_tool("abs_mod_tool")


def test_core_tools_json_still_loads_with_absolute_modules():
    core = json.loads((packages.BACKEND_DIR / "toolbox" / "tools.json").read_text("utf-8"))
    assert core["tools"] and all(not t["module"].startswith(".") for t in core["tools"])
    assert toolbox.has_tool("web_scraper")


@pytest.mark.parametrize("handler", ["os:system", "toolbox.tools.mem_tool:x"])
def test_action_handler_and_health_check_must_be_relative(handler):
    base = {"id": "p", "version": "1", "name": "p"}
    with pytest.raises(Exception, match="relative to the package"):
        PackageManifest.model_validate({**base, "health_check": handler})
    with pytest.raises(Exception, match="relative to the package"):
        PackageManifest.model_validate(
            {**base, "actions": [{"id": "a", "handler": handler}]}
        )


# ---------------------------------------------------------------------------
# uninstall --purge
# ---------------------------------------------------------------------------

_SCHEMA = """
-- CREATE TABLE commented_out (id INTEGER);
CREATE TABLE IF NOT EXISTS purge_items (id INTEGER PRIMARY KEY);
CREATE TABLE "purge_extra" (id INTEGER);
CREATE TABLE people (id INTEGER);
CREATE INDEX IF NOT EXISTS idx_purge ON purge_items(id);
"""


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "rona.db"
    conn = sqlite3.connect(path)
    # "people" is a core table (and the fixture package's schema tries to
    # claim it); "unrelated" belongs to nobody in particular.
    conn.execute("CREATE TABLE people (id INTEGER)")
    conn.execute("CREATE TABLE unrelated (id INTEGER)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


def _tables(path):
    conn = sqlite3.connect(path)
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def _purge_package(catalog, manager_env, pid, tmp_db_path):  # noqa: F811
    catalog(
        pid,
        manifest_extra={
            "schema_sql": "schema.sql",
            "config": [
                {"key": "api_key", "target": "env", "env_var": "PURGE_API_KEY", "secret": True},
                {"key": "other", "target": "env", "env_var": "PURGE_OTHER"},
                {"key": "mode", "target": "config", "default": "x"},
            ],
        },
        extra_files={"schema.sql": _SCHEMA.replace("people", "people_shadow_x")},
    )
    manager_env.append(pid)
    manager.install(
        pid,
        source=catalog.source_spec,
        answers={pid: {"api_key": "sekret", "other": "o", "mode": "y"}},
    )


def test_purge_removes_env_keys_and_package_tables(catalog, manager_env, tmp_db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(db, "DB_PATH", tmp_db)
    _purge_package(catalog, manager_env, "purge_pkg", tmp_db)
    # Plant a core-named table creation in the package schema too.
    schema = packages.package_dir("purge_pkg") / "schema.sql"
    schema.write_text(_SCHEMA, encoding="utf-8")  # includes CREATE TABLE people
    assert {"purge_items", "purge_extra"} <= _tables(tmp_db)
    env_text = packages.ENV_PATH.read_text(encoding="utf-8")
    assert "PURGE_API_KEY=sekret" in env_text

    result = manager.uninstall("purge_pkg", purge=True)

    assert sorted(result.removed_env_keys) == ["PURGE_API_KEY", "PURGE_OTHER"]
    assert sorted(result.dropped_tables) == ["purge_extra", "purge_items"]
    remaining = packages.ENV_PATH.read_text(encoding="utf-8")
    assert "PURGE_" not in remaining
    assert "EXISTING_KEY=leave_me_alone" in remaining
    tables = _tables(tmp_db)
    assert "purge_items" not in tables and "purge_extra" not in tables
    assert {"people", "unrelated"} <= tables  # core + foreign tables untouched


def test_non_purge_uninstall_keeps_env_keys_and_tables(catalog, manager_env, tmp_db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(db, "DB_PATH", tmp_db)
    _purge_package(catalog, manager_env, "keep_pkg", tmp_db)

    result = manager.uninstall("keep_pkg")

    assert result.removed_env_keys == [] and result.dropped_tables == []
    assert "PURGE_API_KEY=sekret" in packages.ENV_PATH.read_text(encoding="utf-8")
    assert "purge_items" in _tables(tmp_db)


def test_purge_keeps_env_key_shared_with_another_package(catalog, manager_env, tmp_db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(db, "DB_PATH", tmp_db)
    _purge_package(catalog, manager_env, "owner_pkg", tmp_db)
    catalog(
        "sharer_pkg",
        manifest_extra={"config": [{"key": "k", "target": "env", "env_var": "PURGE_OTHER"}]},
    )
    manager_env.append("sharer_pkg")
    manager.install("sharer_pkg", source=catalog.source_spec, answers={"sharer_pkg": {"k": "o"}})

    result = manager.uninstall("owner_pkg", purge=True)

    assert result.removed_env_keys == ["PURGE_API_KEY"]
    assert "PURGE_OTHER=o" in packages.ENV_PATH.read_text(encoding="utf-8")


def test_purge_without_declared_schema_or_env_is_harmless(catalog, manager_env, tmp_db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(db, "DB_PATH", tmp_db)
    catalog("plain_pkg", tools=[])
    manager_env.append("plain_pkg")
    manager.install("plain_pkg", source=catalog.source_spec)

    result = manager.uninstall("plain_pkg", purge=True)

    assert result.removed_env_keys == [] and result.dropped_tables == []
    assert {"people", "unrelated"} <= _tables(tmp_db)


def test_table_name_parser_is_conservative():
    names = manager._create_table_names(
        '/* CREATE TABLE in_block (x) */ CREATE TABLE a (x);\n-- CREATE TABLE c (x)\n'
        'create table if not exists "b" (x); CREATE VIRTUAL TABLE v USING fts5(x);'
    )
    assert names == ["a", "b", "v"]
    core = manager._core_table_names()
    assert {"people", "memories", "tasks", "conversation_registry"} <= core
