"""Tests for toolbox.manager: install/configure/health-check/rollback and
uninstall, driven against a LocalSource catalog built under tmp_path so
nothing here touches the real Rona Tools repo or the developer's real .env.
"""

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from toolbox import manager, packages, registry, sources
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
        declare_in_index: bool = True,
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
        entry = {"id": package_id, "version": "0.1.0", "name": package_id, "description": ""}
        if declare_in_index:
            # The real catalog mirrors these two manifest fields into
            # index.json so a dependency plan can be built without
            # downloading anything. declare_in_index=False reproduces an
            # older catalog that doesn't.
            entry["kind"] = manifest.get("kind", "tool")
            entry["requires"] = manifest.get("requires", [])
        data["packages"].append(entry)
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
            shutil.rmtree(packages.preserved_dir(pid), ignore_errors=True)
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

    result = manager.uninstall("base_pkg", force=True)
    assert result.dependents == ["leaf_pkg"]
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


# ---------------------------------------------------------------------------
# Package actions
# ---------------------------------------------------------------------------


def _action_manifest(action_extra: dict | None = None) -> dict:
    action = {"id": "do_thing", "label": "Do the thing", "handler": ".actions:do_thing"}
    action.update(action_extra or {})
    return {"actions": [action]}


def test_action_returns_ok_with_data(catalog, manager_env):
    catalog(
        "act_ok",
        manifest_extra=_action_manifest(),
        tools=[],
        extra_files={
            "actions.py": (
                "def do_thing(config, params, state):\n"
                "    return {'status': 'ok', 'message': 'done', 'data': {'n': 1}}\n"
            )
        },
    )
    manager_env.append("act_ok")
    manager.install("act_ok", source=catalog.source_spec)

    result = manager.run_action("act_ok", "do_thing")
    assert result.ok
    assert result.message == "done"
    assert result.data == {"n": 1}


def test_action_receives_config_and_params(catalog, manager_env):
    catalog(
        "act_args",
        manifest_extra={
            "config": [{"key": "greeting", "target": "config", "required": False}],
            **_action_manifest({"params": [{"key": "who", "required": True}]}),
        },
        tools=[],
        extra_files={
            "actions.py": (
                "def do_thing(config, params, state):\n"
                "    return {'status': 'ok', 'message': "
                "f\"{config.get('greeting')} {params['who']}\"}\n"
            )
        },
    )
    manager_env.append("act_args")
    manager.install("act_args", source=catalog.source_spec)
    manager.configure_installed("act_args", {"greeting": "hi"})

    result = manager.run_action("act_args", "do_thing", {"who": "ada"})
    assert result.message == "hi ada"


def test_action_multi_step_round_trips_state(catalog, manager_env):
    """input_required is the whole point: the handler keeps no session, the
    caller hands its state straight back."""
    catalog(
        "act_steps",
        manifest_extra=_action_manifest({"params": [{"key": "name", "required": True}]}),
        tools=[],
        extra_files={
            "actions.py": (
                "def do_thing(config, params, state):\n"
                "    if state is None:\n"
                "        return {'status': 'input_required', 'message': 'paste it',\n"
                "                'fields': [{'key': 'code', 'label': 'Code'}],\n"
                "                'state': {'name': params['name']}}\n"
                "    return {'status': 'ok',\n"
                "            'message': f\"{state['name']}:{params['code']}\"}\n"
            )
        },
    )
    manager_env.append("act_steps")
    manager.install("act_steps", source=catalog.source_spec)

    first = manager.run_action("act_steps", "do_thing", {"name": "work"})
    assert first.status == "input_required"
    assert [f.key for f in first.fields] == ["code"]
    assert first.state == {"name": "work"}

    second = manager.run_action("act_steps", "do_thing", {"code": "xyz"}, first.state)
    assert second.ok
    assert second.message == "work:xyz"


def test_action_follow_up_step_skips_param_validation(catalog, manager_env):
    """The second call carries the fields the handler asked for, not the
    action's own declared params -- re-checking those would reject it."""
    catalog(
        "act_skip",
        manifest_extra=_action_manifest({"params": [{"key": "name", "required": True}]}),
        tools=[],
        extra_files={
            "actions.py": (
                "def do_thing(config, params, state):\n"
                "    if state is None:\n"
                "        return {'status': 'input_required', 'message': 'more',\n"
                "                'fields': [{'key': 'code'}], 'state': {}}\n"
                "    return {'status': 'ok', 'message': 'fine'}\n"
            )
        },
    )
    manager_env.append("act_skip")
    manager.install("act_skip", source=catalog.source_spec)

    first = manager.run_action("act_skip", "do_thing", {"name": "x"})
    assert first.status == "input_required"
    assert manager.run_action("act_skip", "do_thing", {"code": "c"}, first.state).ok


# A lambda can't be serialised, so this state would survive a CLI round trip
# and then break the moment the same action ran over HTTP.
_UNSERIALISABLE_STATE_BODY = (
    "    return {'status': 'input_required', 'fields': [{'key': 'a'}],\n"
    "            'state': {'f': lambda: 1}}\n"
)


@pytest.mark.parametrize(
    "body, expected_fragment",
    [
        ("    return 'not a dict'\n", "did not return a dict"),
        ("    return {'status': 'weird'}\n", "unknown status"),
        (
            "    return {'status': 'input_required', 'fields': []}\n",
            "declared no fields",
        ),
        (_UNSERIALISABLE_STATE_BODY, "not JSON-serialisable"),
        ("    raise RuntimeError('boom')\n", "action raised: boom"),
    ],
)
def test_action_malformed_return_becomes_error_result(
    catalog, manager_env, body, expected_fragment
):
    """A third-party package's bug must read as a failed action, never as a
    crashed backend."""
    package_id = f"act_bad_{abs(hash(expected_fragment)) % 10000}"
    catalog(
        package_id,
        manifest_extra=_action_manifest(),
        tools=[],
        extra_files={"actions.py": "def do_thing(config, params, state):\n" + body},
    )
    manager_env.append(package_id)
    manager.install(package_id, source=catalog.source_spec)

    result = manager.run_action(package_id, "do_thing")
    assert result.status == "error"
    assert expected_fragment in result.message


def test_action_unknown_id_and_missing_param_raise(catalog, manager_env):
    catalog(
        "act_strict",
        manifest_extra=_action_manifest({"params": [{"key": "who", "required": True}]}),
        tools=[],
        extra_files={
            "actions.py": (
                "def do_thing(config, params, state):\n"
                "    return {'status': 'ok', 'message': 'ok'}\n"
            )
        },
    )
    manager_env.append("act_strict")
    manager.install("act_strict", source=catalog.source_spec)

    with pytest.raises(ManagerError, match="no action"):
        manager.run_action("act_strict", "nope")
    with pytest.raises(ManagerError, match="needs: who"):
        manager.run_action("act_strict", "do_thing")


def test_action_cli_only_is_refused_when_not_allowed(catalog, manager_env):
    catalog(
        "act_local",
        manifest_extra=_action_manifest({"cli_only": True}),
        tools=[],
        extra_files={
            "actions.py": (
                "def do_thing(config, params, state):\n"
                "    return {'status': 'ok', 'message': 'ok'}\n"
            )
        },
    )
    manager_env.append("act_local")
    manager.install("act_local", source=catalog.source_spec)

    assert manager.run_action("act_local", "do_thing").ok
    with pytest.raises(ManagerError, match="only be run from a terminal"):
        manager.run_action("act_local", "do_thing", allow_cli_only=False)


def test_action_bad_handler_spec_raises(catalog, manager_env):
    catalog(
        "act_nohandler",
        manifest_extra=_action_manifest({"handler": ".actions:missing_function"}),
        tools=[],
        extra_files={"actions.py": "x = 1\n"},
    )
    manager_env.append("act_nohandler")
    manager.install("act_nohandler", source=catalog.source_spec)

    with pytest.raises(manager.ActionError):
        manager.run_action("act_nohandler", "do_thing")


def test_run_action_on_missing_package_raises(manager_env):
    with pytest.raises(ManagerError, match="not installed"):
        manager.run_action("never_installed", "do_thing")


# ---------------------------------------------------------------------------
# Post-install configuration
# ---------------------------------------------------------------------------


def test_configure_installed_writes_and_rechecks(catalog, manager_env):
    catalog(
        "cfg_pkg",
        manifest_extra={
            "config": [{"key": "accounts", "type": "list", "target": "config", "required": False}],
            "health_check": ".health:check",
        },
        tools=[],
        extra_files={
            "health.py": (
                "def check(config):\n"
                "    accounts = config.get('accounts') or []\n"
                "    return {'ok': bool(accounts), 'detail': f'{len(accounts)} account(s)'}\n"
            )
        },
    )
    manager_env.append("cfg_pkg")
    # Installs unhealthy on purpose: nothing is configured yet, which is
    # exactly the state post-install configuration exists to get out of.
    manager.install("cfg_pkg", source=catalog.source_spec, keep_on_health_failure=True)
    assert not manager.verify_installed("cfg_pkg").ok

    result = manager.configure_installed("cfg_pkg", {"accounts": ["work", "home"]})
    assert result.ok
    assert packages.read_config_file("cfg_pkg")["accounts"] == ["work", "home"]


def test_configure_installed_keeps_untouched_values(catalog, manager_env):
    catalog(
        "cfg_keep",
        manifest_extra={
            "config": [
                {"key": "one", "target": "config", "required": False},
                {"key": "two", "target": "config", "required": False},
            ]
        },
        tools=[],
    )
    manager_env.append("cfg_keep")
    manager.install("cfg_keep", source=catalog.source_spec)
    manager.configure_installed("cfg_keep", {"one": "a", "two": "b"})

    manager.configure_installed("cfg_keep", {"two": "changed"})
    stored = packages.read_config_file("cfg_keep")
    assert stored == {"one": "a", "two": "changed"}


def test_configure_installed_does_not_recopy_a_file_field(catalog, manager_env, tmp_path):
    """The resolved value of a "file" field is the copy already sitting in the
    package directory; merging it back must not try to copy it onto itself."""
    source_file = tmp_path / "creds.json"
    source_file.write_text('{"installed": {}}', encoding="utf-8")
    catalog(
        "cfg_file",
        manifest_extra={
            "config": [
                {
                    "key": "creds",
                    "target": "file",
                    "dest_filename": "creds.json",
                    "required": True,
                },
                {"key": "note", "target": "config", "required": False},
            ]
        },
        tools=[],
    )
    manager_env.append("cfg_file")
    manager.install(
        "cfg_file",
        source=catalog.source_spec,
        answers={"cfg_file": {"creds": str(source_file)}},
    )

    manager.configure_installed("cfg_file", {"note": "hello"})
    assert (packages.package_dir("cfg_file") / "creds.json").is_file()
    assert packages.read_config_file("cfg_file")["note"] == "hello"


def test_configure_installed_rejects_unknown_field(catalog, manager_env):
    catalog("cfg_strict", tools=[])
    manager_env.append("cfg_strict")
    manager.install("cfg_strict", source=catalog.source_spec)

    with pytest.raises(ManagerError, match="no config field"):
        manager.configure_installed("cfg_strict", {"nope": 1})


# ---------------------------------------------------------------------------
# Dependency plans
# ---------------------------------------------------------------------------


def _plan(catalog_fixture, package_id):
    return manager.resolve_plan(
        package_id, sources.parse_source(catalog_fixture.source_spec)
    )


def test_resolve_plan_lists_dependencies_first(catalog, manager_env):
    catalog("plan_base", manifest_extra={"kind": "library"}, tools=[])
    catalog("plan_leaf", manifest_extra={"requires": ["plan_base"]}, tools=[])

    plan, complete = _plan(catalog, "plan_leaf")
    assert complete
    assert [(e.id, e.reason) for e in plan] == [
        ("plan_base", "dependency"),
        ("plan_leaf", "requested"),
    ]
    assert plan[0].kind == "library"
    assert not any(e.already_installed for e in plan)


def test_resolve_plan_marks_already_installed(catalog, manager_env):
    catalog("plan_dep", manifest_extra={"kind": "library"}, tools=[])
    catalog("plan_top", manifest_extra={"requires": ["plan_dep"]}, tools=[])
    manager_env.extend(["plan_dep"])
    manager.install("plan_dep", source=catalog.source_spec)

    plan, _ = _plan(catalog, "plan_top")
    assert [e.already_installed for e in plan] == [True, False]


def test_resolve_plan_is_incomplete_when_the_index_is_silent(catalog, manager_env):
    """An older catalog that doesn't publish requires must not be read as
    'this package has no dependencies'."""
    catalog("plan_quiet", manifest_extra={"requires": ["whatever"]}, declare_in_index=False)

    plan, complete = _plan(catalog, "plan_quiet")
    assert not complete
    assert [e.id for e in plan] == ["plan_quiet"]


def test_resolve_plan_detects_a_cycle(catalog, manager_env):
    catalog("plan_a", manifest_extra={"requires": ["plan_b"]}, tools=[])
    catalog("plan_b", manifest_extra={"requires": ["plan_a"]}, tools=[])

    with pytest.raises(manager.DependencyCycle):
        _plan(catalog, "plan_a")


def test_resolve_plan_reports_a_missing_dependency(catalog, manager_env):
    catalog("plan_orphan", manifest_extra={"requires": ["absent_pkg"]}, tools=[])

    with pytest.raises(sources.SourceError, match="absent_pkg"):
        _plan(catalog, "plan_orphan")


def test_on_plan_rejection_installs_nothing(catalog, manager_env):
    catalog("gate_base", manifest_extra={"kind": "library"}, tools=[])
    catalog("gate_leaf", manifest_extra={"requires": ["gate_base"]}, tools=[])
    manager_env.extend(["gate_base", "gate_leaf"])
    seen = []

    with pytest.raises(InstallCancelled):
        manager.install(
            "gate_leaf",
            source=catalog.source_spec,
            on_plan=lambda plan, complete: seen.append(plan) or False,
        )

    assert [e.id for e in seen[0]] == ["gate_base", "gate_leaf"]
    assert not manager.is_installed("gate_base")
    assert not manager.is_installed("gate_leaf")


def test_on_plan_is_skipped_without_new_dependencies(catalog, manager_env):
    """Nothing extra is being pulled in, so there is nothing to warn about."""
    catalog("gate_solo", tools=[])
    manager_env.append("gate_solo")
    calls = []

    manager.install(
        "gate_solo",
        source=catalog.source_spec,
        on_plan=lambda plan, complete: calls.append(plan) or False,
    )
    assert calls == []
    assert manager.is_installed("gate_solo")


# ---------------------------------------------------------------------------
# User data across uninstall / reinstall
# ---------------------------------------------------------------------------


def _token(package_id: str, name: str = "work") -> Path:
    path = packages.package_dir(package_id) / f"token_{name}.json"
    path.write_text('{"token": "secret"}', encoding="utf-8")
    return path


def test_uninstall_preserves_user_data_by_default(catalog, manager_env):
    catalog("ud_keep", manifest_extra={"user_data_globs": ["token_*.json"]}, tools=[])
    manager_env.append("ud_keep")
    manager.install("ud_keep", source=catalog.source_spec)
    _token("ud_keep")

    result = manager.uninstall("ud_keep")
    assert result.preserved == ["token_work.json"]
    assert not manager.is_installed("ud_keep")
    assert (packages.preserved_dir("ud_keep") / "token_work.json").is_file()


def test_reinstall_restores_preserved_user_data(catalog, manager_env):
    catalog("ud_round", manifest_extra={"user_data_globs": ["token_*.json"]}, tools=[])
    manager_env.append("ud_round")
    manager.install("ud_round", source=catalog.source_spec)
    _token("ud_round")
    manager.uninstall("ud_round")
    _purge_module_cache("ud_round")

    staged = manager.install("ud_round", source=catalog.source_spec)
    assert staged[0].restored_user_data == ["token_work.json"]
    restored = packages.package_dir("ud_round") / "token_work.json"
    assert restored.read_text(encoding="utf-8") == '{"token": "secret"}'
    assert not packages.preserved_dir("ud_round").exists()


def test_uninstall_purge_deletes_user_data(catalog, manager_env):
    catalog("ud_purge", manifest_extra={"user_data_globs": ["token_*.json"]}, tools=[])
    manager_env.append("ud_purge")
    manager.install("ud_purge", source=catalog.source_spec)
    _token("ud_purge")

    result = manager.uninstall("ud_purge", purge=True)
    assert result.preserved == []
    assert not packages.preserved_dir("ud_purge").exists()


def test_on_user_data_declining_deletes(catalog, manager_env):
    catalog("ud_ask", manifest_extra={"user_data_globs": ["token_*.json"]}, tools=[])
    manager_env.append("ud_ask")
    manager.install("ud_ask", source=catalog.source_spec)
    _token("ud_ask")
    asked = []

    result = manager.uninstall(
        "ud_ask", on_user_data=lambda pid, paths: asked.append((pid, paths)) or False
    )
    assert asked[0][0] == "ud_ask"
    assert [p.name for p in asked[0][1]] == ["token_work.json"]
    assert result.preserved == []
    assert not packages.preserved_dir("ud_ask").exists()


def test_user_data_globs_cannot_escape_the_package_directory(catalog, manager_env):
    catalog("ud_escape", manifest_extra={"user_data_globs": ["../*.json"]}, tools=[])
    manager_env.append("ud_escape")
    manager.install("ud_escape", source=catalog.source_spec)

    manifest = packages.load_manifest(packages.package_dir("ud_escape"))
    assert packages.user_data_paths(manifest) == []


# ---------------------------------------------------------------------------
# The manager's own command line
# ---------------------------------------------------------------------------


def _json_output(capsys) -> dict:
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_cli_verify_reports_why_it_is_unhealthy(catalog, manager_env, capsys):
    """_emit prints payload["error"] when ok is false, so a bare
    {"ok": False, "detail": ...} printed nothing but "error: None" -- losing
    the one thing the user needs."""
    catalog(
        "cli_sick",
        manifest_extra={"health_check": ".health:check"},
        tools=[],
        extra_files={
            "health.py": "def check(config):\n    return {'ok': False, 'detail': 'needs a key'}\n"
        },
    )
    manager_env.append("cli_sick")
    manager.install("cli_sick", source=catalog.source_spec, keep_on_health_failure=True)

    assert manager.main(["verify", "cli_sick"]) == 1
    assert "needs a key" in capsys.readouterr().err


def test_cli_config_shows_then_sets(catalog, manager_env, capsys):
    catalog(
        "cli_cfg",
        manifest_extra={
            "config": [
                {"key": "token", "target": "env", "env_var": "CLI_CFG_TOKEN",
                 "secret": True, "required": False},
                {"key": "accounts", "type": "list", "target": "config", "required": False},
            ]
        },
        tools=[],
    )
    manager_env.append("cli_cfg")
    manager.install("cli_cfg", source=catalog.source_spec)

    assert manager.main(["--json", "config", "cli_cfg"]) == 0
    fields = {f["key"]: f for f in _json_output(capsys)["fields"]}
    assert fields["accounts"]["value"] is None and not fields["accounts"]["set"]
    assert fields["token"]["secret"] is True

    assert manager.main(
        ["--json", "config", "cli_cfg", "--set", "accounts=work,home",
         "--set", "token=s3cret"]
    ) == 0
    assert sorted(_json_output(capsys)["changed"]) == ["accounts", "token"]
    assert packages.read_config_file("cli_cfg")["accounts"] == ["work", "home"]

    # Reading it back must never hand the secret out again.
    manager.main(["--json", "config", "cli_cfg"])
    fields = {f["key"]: f for f in _json_output(capsys)["fields"]}
    assert fields["token"]["set"] is True
    assert fields["token"]["value"] is None
    assert fields["accounts"]["value"] == ["work", "home"]

    os.environ.pop("CLI_CFG_TOKEN", None)


def test_cli_config_rejects_an_unknown_key(catalog, manager_env, capsys):
    catalog("cli_cfg_bad", tools=[])
    manager_env.append("cli_cfg_bad")
    manager.install("cli_cfg_bad", source=catalog.source_spec)

    assert manager.main(["--json", "config", "cli_cfg_bad", "--set", "nope=1"]) == 1
    assert "no config field" in _json_output(capsys)["error"]


def test_cli_actions_and_run(catalog, manager_env, capsys):
    catalog(
        "cli_act",
        manifest_extra={
            "actions": [
                {
                    "id": "greet",
                    "label": "Greet",
                    "handler": ".actions:greet",
                    "params": [{"key": "who", "required": True}],
                },
                {"id": "wipe", "handler": ".actions:greet", "cli_only": True},
            ]
        },
        tools=[],
        extra_files={
            "actions.py": (
                "def greet(config, params, state):\n"
                "    return {'status': 'ok', 'message': f\"hi {params.get('who')}\"}\n"
            )
        },
    )
    manager_env.append("cli_act")
    manager.install("cli_act", source=catalog.source_spec)

    assert manager.main(["--json", "actions", "cli_act"]) == 0
    actions = {a["id"]: a for a in _json_output(capsys)["actions"]}
    assert actions["greet"]["params"][0]["key"] == "who"
    assert actions["wipe"]["cli_only"] is True

    assert manager.main(["--json", "run", "cli_act", "greet", "--set", "who=ada"]) == 0
    assert _json_output(capsys)["message"] == "hi ada"


def test_cli_run_without_a_required_param_fails_under_yes(catalog, manager_env, capsys):
    catalog(
        "cli_act_strict",
        manifest_extra={
            "actions": [
                {
                    "id": "greet",
                    "handler": ".actions:greet",
                    "params": [{"key": "who", "required": True}],
                }
            ]
        },
        tools=[],
        extra_files={
            "actions.py": (
                "def greet(config, params, state):\n"
                "    return {'status': 'ok', 'message': 'hi'}\n"
            )
        },
    )
    manager_env.append("cli_act_strict")
    manager.install("cli_act_strict", source=catalog.source_spec)

    assert manager.main(["--json", "run", "cli_act_strict", "greet", "--yes"]) == 1
    assert "use --set" in _json_output(capsys)["error"]


def test_cli_available_carries_dependency_metadata(catalog, manager_env, capsys):
    catalog("cli_dep", manifest_extra={"kind": "library"}, tools=[])
    catalog("cli_top", manifest_extra={"requires": ["cli_dep"]}, tools=[])
    manager_env.append("cli_dep")
    manager.install("cli_dep", source=catalog.source_spec)

    assert manager.main(["--json", "available", "--source", catalog.source_spec]) == 0
    entries = {p["id"]: p for p in _json_output(capsys)["packages"]}
    assert entries["cli_top"]["requires"] == ["cli_dep"]
    assert entries["cli_dep"]["kind"] == "library"
    assert entries["cli_dep"]["installed"] is True
    assert entries["cli_top"]["installed"] is False


def test_cli_install_reports_a_catalog_failure_as_json(manager_env, capsys, tmp_path):
    """SourceError is not a ManagerError: this used to escape _cli_install as a
    raw traceback, which the CLI then reported as 'no output from the manager'
    instead of the actual reason."""
    assert manager.main(
        ["--json", "install", "anything", "--source", f"local:{tmp_path}", "--yes"]
    ) == 1
    assert "index.json not found" in _json_output(capsys)["error"]
