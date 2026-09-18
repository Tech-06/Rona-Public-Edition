"""Tests for toolbox.manager: install/configure/health-check/rollback and
uninstall, driven against a LocalSource catalog built under tmp_path so
nothing here touches the real Rona Tools repo or the developer's real .env.
"""

import json
import os
import shutil
import sys

import pytest

from toolbox import manager, packages, registry
from toolbox.manager import (
    HealthCheckFailed,
    InstallCancelled,
    ManagerError,
    ToolNameConflict,
)


def _purge_module_cache(package_id: str) -> None:
    prefix = f"toolbox.custom.{package_id}"
    for name in [n for n in sys.modules if n == prefix or n.startswith(prefix + ".")]:
        del sys.modules[name]


@pytest.fixture
def catalog(tmp_path):
    """A LocalSource-style catalog directory: tests add packages to it."""
    root = tmp_path / "catalog"
    (root / "packages").mkdir(parents=True)
    index = {"catalog_version": 1, "packages": []}
    (root / "index.json").write_text(json.dumps(index), encoding="utf-8")

    def add_package(
        package_id: str,
        manifest_extra: dict | None = None,
        tools: list[dict] | None = None,
        module_source: str = "",
        extra_files: dict[str, str] | None = None,
    ):
        manifest = {
            "id": package_id,
            "version": "0.1.0",
            "kind": "tool",
            "name": package_id,
            "description": "fixture",
        }
        manifest.update(manifest_extra or {})
        pkg_dir = root / "packages" / package_id
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (pkg_dir / "tools.json").write_text(
            json.dumps({"tools": tools or []}), encoding="utf-8"
        )
        if module_source:
            # Name the module file after the first tool's declared module
            # (".foo" -> "foo.py") so `.{tool_name}` conventions used by
            # _simple_tool() resolve correctly; fall back to the package id
            # for tool-less (library) packages.
            mod_name = tools[0]["module"].lstrip(".") if tools else package_id
            (pkg_dir / f"{mod_name}.py").write_text(module_source, encoding="utf-8")
        for name, content in (extra_files or {}).items():
            (pkg_dir / name).write_text(content, encoding="utf-8")

        data = json.loads((root / "index.json").read_text(encoding="utf-8"))
        data["packages"].append(
            {"id": package_id, "version": "0.1.0", "name": package_id, "description": ""}
        )
        (root / "index.json").write_text(json.dumps(data), encoding="utf-8")
        return pkg_dir

    add_package.source_spec = f"local:{root}"
    return add_package


@pytest.fixture
def manager_env(tmp_path, monkeypatch):
    fake_env = tmp_path / ".env"
    fake_env.write_text("EXISTING_KEY=leave_me_alone\n", encoding="utf-8")
    monkeypatch.setattr(packages, "ENV_PATH", fake_env)
    prior_lock = packages.read_lockfile()
    created: list[str] = []
    try:
        yield created
    finally:
        for pid in created:
            shutil.rmtree(packages.package_dir(pid), ignore_errors=True)
            _purge_module_cache(pid)
        packages.write_lockfile(prior_lock)
        registry.reload_registry()
        for key in ("TESTPKG_API_KEY", "RETRY_KEY", "FRESH_KEY", "EXISTING_KEY"):
            os.environ.pop(key, None)


def _simple_tool(name: str) -> dict:
    return {
        "name": name,
        "description": "fixture tool",
        "module": f".{name}",
        "function": name,
        "parameters": {"type": "object", "properties": {}, "required": []},
        "requires_confirmation": False,
        "background": True,
    }


def test_install_simple_package_no_config(catalog, manager_env):
    catalog(
        "pkg_a",
        tools=[_simple_tool("pkg_a_tool")],
        module_source="def pkg_a_tool():\n    return {'success': True}\n",
    )
    manager_env.append("pkg_a")

    staged = manager.install("pkg_a", source=catalog.source_spec)

    assert [s.manifest.id for s in staged] == ["pkg_a"]
    assert manager.is_installed("pkg_a")
    import toolbox

    assert toolbox.has_tool("pkg_a_tool")
    lock = packages.read_lockfile()
    assert "pkg_a" in lock["packages"]
    assert lock["packages"]["pkg_a"]["source"] == catalog.source_spec


def test_install_rolls_back_on_tool_name_conflict(catalog, manager_env):
    catalog(
        "pkg_conflict",
        tools=[_simple_tool("web_scraper")],  # a real core tool name
        module_source="def web_scraper():\n    return {'success': True}\n",
    )
    manager_env.append("pkg_conflict")

    with pytest.raises(ToolNameConflict):
        manager.install("pkg_conflict", source=catalog.source_spec)

    assert not manager.is_installed("pkg_conflict")


def test_install_with_env_config_success(catalog, manager_env):
    health_source = (
        "def check(config):\n"
        "    ok = bool(config.get('api_key'))\n"
        "    return {'ok': ok, 'detail': 'ok' if ok else 'missing key'}\n"
    )
    catalog(
        "pkg_env",
        manifest_extra={
            "config": [
                {
                    "key": "api_key",
                    "target": "env",
                    "env_var": "TESTPKG_API_KEY",
                    "secret": True,
                    "required": True,
                }
            ],
            "health_check": ".health:check",
        },
        tools=[_simple_tool("pkg_env_tool")],
        module_source="def pkg_env_tool():\n    return {'success': True}\n",
        extra_files={"health.py": health_source},
    )
    manager_env.append("pkg_env")

    staged = manager.install(
        "pkg_env",
        source=catalog.source_spec,
        answers={"pkg_env": {"api_key": "sekret"}},
    )

    assert manager.is_installed("pkg_env")
    assert os.environ["TESTPKG_API_KEY"] == "sekret"
    env_text = packages.ENV_PATH.read_text(encoding="utf-8")
    assert "TESTPKG_API_KEY=sekret" in env_text
    assert "EXISTING_KEY=leave_me_alone" in env_text  # untouched
    assert staged[0].manifest.id == "pkg_env"


def test_install_missing_required_config_raises_without_callback(catalog, manager_env):
    catalog(
        "pkg_needs_cfg",
        manifest_extra={
            "config": [{"key": "api_key", "target": "env", "env_var": "X", "required": True}]
        },
        tools=[_simple_tool("pkg_needs_cfg_tool")],
        module_source="def pkg_needs_cfg_tool():\n    return {'success': True}\n",
    )
    manager_env.append("pkg_needs_cfg")

    with pytest.raises(ManagerError):
        manager.install("pkg_needs_cfg", source=catalog.source_spec)

    assert not manager.is_installed("pkg_needs_cfg")


def test_install_rolls_back_on_failing_health_check_no_callback(catalog, manager_env):
    catalog(
        "pkg_unhealthy",
        manifest_extra={"health_check": ".health:check"},
        tools=[_simple_tool("pkg_unhealthy_tool")],
        module_source="def pkg_unhealthy_tool():\n    return {'success': True}\n",
        extra_files={"health.py": "def check(config):\n    return {'ok': False, 'detail': 'nope'}\n"},
    )
    manager_env.append("pkg_unhealthy")

    with pytest.raises(HealthCheckFailed):
        manager.install("pkg_unhealthy", source=catalog.source_spec)

    assert not manager.is_installed("pkg_unhealthy")
    import toolbox

    assert not toolbox.has_tool("pkg_unhealthy_tool")


def test_install_keep_on_health_failure(catalog, manager_env):
    catalog(
        "pkg_keep",
        manifest_extra={"health_check": ".health:check"},
        tools=[_simple_tool("pkg_keep_tool")],
        module_source="def pkg_keep_tool():\n    return {'success': True}\n",
        extra_files={"health.py": "def check(config):\n    return {'ok': False, 'detail': 'nope'}\n"},
    )
    manager_env.append("pkg_keep")

    staged = manager.install(
        "pkg_keep", source=catalog.source_spec, keep_on_health_failure=True
    )

    assert manager.is_installed("pkg_keep")
    assert staged[0].manifest.id == "pkg_keep"


def test_install_retry_then_succeed(catalog, manager_env):
    health_source = (
        "def check(config):\n"
        "    ok = config.get('api_key') == 'correct'\n"
        "    return {'ok': ok, 'detail': 'ok' if ok else 'bad key'}\n"
    )
    catalog(
        "pkg_retry",
        manifest_extra={
            "config": [
                {"key": "api_key", "target": "env", "env_var": "RETRY_KEY", "required": True}
            ],
            "health_check": ".health:check",
        },
        tools=[_simple_tool("pkg_retry_tool")],
        module_source="def pkg_retry_tool():\n    return {'success': True}\n",
        extra_files={"health.py": health_source},
    )
    manager_env.append("pkg_retry")

    calls = {"n": 0}

    def on_health_result(staged, result):
        calls["n"] += 1
        return "retry" if calls["n"] == 1 else "cancel"

    def on_missing_config(staged, fields):
        return {"api_key": "correct"}

    staged = manager.install(
        "pkg_retry",
        source=catalog.source_spec,
        answers={"pkg_retry": {"api_key": "wrong"}},
        on_missing_config=on_missing_config,
        on_health_result=on_health_result,
    )

    assert manager.is_installed("pkg_retry")
    assert os.environ["RETRY_KEY"] == "correct"
    assert staged[0].manifest.id == "pkg_retry"


def test_install_cancel_after_health_failure_rolls_back_and_restores_env(catalog, manager_env):
    catalog(
        "pkg_cancel",
        manifest_extra={
            "config": [
                {"key": "api_key", "target": "env", "env_var": "EXISTING_KEY", "required": True}
            ],
            "health_check": ".health:check",
        },
        tools=[_simple_tool("pkg_cancel_tool")],
        module_source="def pkg_cancel_tool():\n    return {'success': True}\n",
        extra_files={"health.py": "def check(config):\n    return {'ok': False, 'detail': 'no'}\n"},
    )
    manager_env.append("pkg_cancel")

    with pytest.raises(InstallCancelled):
        manager.install(
            "pkg_cancel",
            source=catalog.source_spec,
            answers={"pkg_cancel": {"api_key": "overwritten"}},
            on_health_result=lambda staged, result: "cancel",
        )

    assert not manager.is_installed("pkg_cancel")
    # The pre-existing EXISTING_KEY must be restored to its original value,
    # not left as "overwritten" or deleted.
    env_text = packages.ENV_PATH.read_text(encoding="utf-8")
    assert "EXISTING_KEY=leave_me_alone" in env_text
    assert "overwritten" not in env_text


def test_install_rollback_removes_brand_new_env_key(catalog, manager_env):
    catalog(
        "pkg_newkey",
        manifest_extra={
            "config": [
                {"key": "api_key", "target": "env", "env_var": "FRESH_KEY", "required": True}
            ],
            "health_check": ".health:check",
        },
        tools=[_simple_tool("pkg_newkey_tool")],
        module_source="def pkg_newkey_tool():\n    return {'success': True}\n",
        extra_files={"health.py": "def check(config):\n    return {'ok': False, 'detail': 'no'}\n"},
    )
    manager_env.append("pkg_newkey")

    with pytest.raises(HealthCheckFailed):
        manager.install(
            "pkg_newkey",
            source=catalog.source_spec,
            answers={"pkg_newkey": {"api_key": "temp"}},
        )

    env_text = packages.ENV_PATH.read_text(encoding="utf-8")
    assert "FRESH_KEY" not in env_text


def test_install_stages_and_configures_dependency_first(catalog, manager_env):
    catalog(
        "dep_pkg",
        manifest_extra={
            "kind": "library",
            "config": [
                {"key": "shared_value", "target": "config", "required": True}
            ],
        },
        tools=[],
    )
    catalog(
        "dependent_pkg",
        manifest_extra={"requires": ["dep_pkg"]},
        tools=[_simple_tool("dependent_pkg_tool")],
        module_source="def dependent_pkg_tool():\n    return {'success': True}\n",
    )
    manager_env.extend(["dep_pkg", "dependent_pkg"])

    staged = manager.install(
        "dependent_pkg",
        source=catalog.source_spec,
        answers={"dep_pkg": {"shared_value": "hello"}},
    )

    ids = [s.manifest.id for s in staged]
    assert ids == ["dependent_pkg", "dep_pkg"] or ids == ["dep_pkg", "dependent_pkg"]
    assert manager.is_installed("dep_pkg")
    assert manager.is_installed("dependent_pkg")
    assert packages.read_config_file("dep_pkg") == {"shared_value": "hello"}


def test_dependency_cycle_detected(catalog, manager_env):
    catalog("cycle_a", manifest_extra={"requires": ["cycle_b"]}, tools=[])
    catalog("cycle_b", manifest_extra={"requires": ["cycle_a"]}, tools=[])
    manager_env.extend(["cycle_a", "cycle_b"])

    with pytest.raises(manager.DependencyCycle):
        manager.install("cycle_a", source=catalog.source_spec)


def test_uninstall_blocked_by_dependent_without_force(catalog, manager_env):
    catalog("base_pkg", manifest_extra={"kind": "library"}, tools=[])
    catalog(
        "leaf_pkg",
        manifest_extra={"requires": ["base_pkg"]},
        tools=[_simple_tool("leaf_pkg_tool")],
        module_source="def leaf_pkg_tool():\n    return {'success': True}\n",
    )
    manager_env.extend(["base_pkg", "leaf_pkg"])
    manager.install("leaf_pkg", source=catalog.source_spec)

    with pytest.raises(ManagerError):
        manager.uninstall("base_pkg")
    assert manager.is_installed("base_pkg")

    dependents = manager.uninstall("base_pkg", force=True)
    assert dependents == ["leaf_pkg"]
    assert not manager.is_installed("base_pkg")


def test_uninstall_not_installed_raises(manager_env):
    with pytest.raises(ManagerError):
        manager.uninstall("does_not_exist")


def test_verify_installed_runs_health_check(catalog, manager_env):
    catalog(
        "pkg_verify",
        manifest_extra={"health_check": ".health:check"},
        tools=[_simple_tool("pkg_verify_tool")],
        module_source="def pkg_verify_tool():\n    return {'success': True}\n",
        extra_files={"health.py": "def check(config):\n    return {'ok': True, 'detail': 'fine'}\n"},
    )
    manager_env.append("pkg_verify")
    manager.install("pkg_verify", source=catalog.source_spec)

    result = manager.verify_installed("pkg_verify")
    assert result.ok
    assert result.detail == "fine"
