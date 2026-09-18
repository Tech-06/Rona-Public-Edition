"""Tests for the custom tool package mechanism (toolbox.packages / merging
into toolbox.registry).

These tests create small, throwaway package directories directly under the
real ``toolbox/custom/`` directory (the only place Python's import system
can find them as ``toolbox.custom.<id>.<module>``), exercise
``registry.reload_registry()`` against them, and always clean up -- both the
files on disk and any ``sys.modules`` cache entries -- in a ``finally``
block so a failed test cannot leak state into the next one.
"""

import json
import shutil
import sys

import pytest

import toolbox
from toolbox import packages, registry

CUSTOM_DIR = packages.CUSTOM_DIR


def _purge_module_cache(package_id: str) -> None:
    prefix = f"toolbox.custom.{package_id}"
    for name in [n for n in sys.modules if n == prefix or n.startswith(prefix + ".")]:
        del sys.modules[name]


@pytest.fixture
def fixture_package():
    """Create a package dir, yield a helper to write files into it, tear down after."""
    created: list[str] = []

    def make(
        package_id: str,
        manifest: dict,
        tools: dict,
        module_source: str,
        module_name: str | None = None,
        config: dict | None = None,
    ):
        pkg_dir = CUSTOM_DIR / package_id
        pkg_dir.mkdir(parents=True, exist_ok=False)
        created.append(package_id)
        (pkg_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        (pkg_dir / "tools.json").write_text(
            json.dumps(tools, ensure_ascii=False), encoding="utf-8"
        )
        mod = module_name or package_id
        (pkg_dir / f"{mod}.py").write_text(module_source, encoding="utf-8")
        if config is not None:
            (pkg_dir / "config.json").write_text(
                json.dumps(config, ensure_ascii=False), encoding="utf-8"
            )
        return pkg_dir

    try:
        yield make
    finally:
        for package_id in created:
            shutil.rmtree(CUSTOM_DIR / package_id, ignore_errors=True)
            _purge_module_cache(package_id)
        registry.reload_registry()


def _manifest(package_id: str, **overrides) -> dict:
    base = {
        "id": package_id,
        "version": "0.1.0",
        "kind": "tool",
        "name": package_id,
        "description": "test fixture package",
        "provides": [package_id],
    }
    base.update(overrides)
    return base


def _tools(name: str, module: str = None) -> dict:
    return {
        "tools": [
            {
                "name": name,
                "description": "test tool",
                "module": module or f".{name}",
                "function": name,
                "parameters": {"type": "object", "properties": {}, "required": []},
                "requires_confirmation": False,
                "background": True,
            }
        ]
    }


def test_installed_package_merges_into_registry(fixture_package):
    fixture_package(
        "sample_pkg",
        _manifest("sample_pkg"),
        _tools("sample_tool"),
        "def sample_tool():\n    return {'success': True}\n",
        module_name="sample_tool",
    )
    registry.reload_registry()

    assert toolbox.has_tool("sample_tool")
    assert toolbox.get_tool("sample_tool")() == {"success": True}
    ids = {m.id for m in toolbox.installed_packages()}
    assert "sample_pkg" in ids
    assert toolbox.load_warnings() == []


def test_core_tools_still_present_alongside_custom(fixture_package):
    base_count = len(toolbox.iter_specs())
    fixture_package(
        "sample_pkg2",
        _manifest("sample_pkg2"),
        _tools("sample_tool2"),
        "def sample_tool2():\n    return {'success': True}\n",
        module_name="sample_tool2",
    )
    registry.reload_registry()

    assert toolbox.has_tool("sample_tool2")
    assert toolbox.has_tool("web_scraper")  # a core tool, untouched
    assert len(toolbox.iter_specs()) == base_count + 1


def test_tool_name_conflict_with_core_is_skipped_not_fatal(fixture_package):
    fixture_package(
        "conflict_pkg",
        _manifest("conflict_pkg", provides=["web_scraper"]),
        _tools("web_scraper"),  # collides with the core tool of the same name
        "def web_scraper(url=''):\n    return {'success': True, 'content': 'fake'}\n",
        module_name="web_scraper",
    )
    registry.reload_registry()

    # Core tool wins; registry did not crash. The package itself still shows
    # up as installed (its manifest/tools.json were valid) -- only the
    # conflicting tool entry was dropped.
    assert toolbox.get_tool("web_scraper").__module__ == "toolbox.tools.web_scraper"
    assert any("web_scraper" in w for w in toolbox.load_warnings())
    assert "conflict_pkg" in {m.id for m in toolbox.installed_packages()}


def test_missing_manifest_is_skipped_with_warning(fixture_package):
    pkg_dir = CUSTOM_DIR / "broken_pkg"
    pkg_dir.mkdir(parents=True, exist_ok=False)
    try:
        registry.reload_registry()
        assert not toolbox.has_tool("anything_from_broken_pkg")
        assert any("broken_pkg" in w for w in toolbox.load_warnings())
        # The rest of the registry (core tools) must still be intact.
        assert toolbox.has_tool("web_scraper")
    finally:
        shutil.rmtree(pkg_dir, ignore_errors=True)
        registry.reload_registry()


def test_import_error_in_one_tool_does_not_break_others_in_same_package(fixture_package):
    fixture_package(
        "half_broken_pkg",
        _manifest("half_broken_pkg", provides=["good_tool", "bad_tool"]),
        {
            "tools": [
                {
                    "name": "good_tool",
                    "description": "works",
                    "module": ".half_broken_pkg",
                    "function": "good_tool",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                    "requires_confirmation": False,
                    "background": True,
                },
                {
                    "name": "bad_tool",
                    "description": "missing function",
                    "module": ".half_broken_pkg",
                    "function": "does_not_exist",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                    "requires_confirmation": False,
                    "background": True,
                },
            ]
        },
        "def good_tool():\n    return {'success': True}\n",
    )
    registry.reload_registry()

    assert toolbox.has_tool("good_tool")
    assert not toolbox.has_tool("bad_tool")
    assert any("half_broken_pkg" in w for w in toolbox.load_warnings())


def test_config_placeholder_resolved_from_config_json(fixture_package):
    manifest = _manifest(
        "configured_pkg",
        provides=["configured_tool"],
        config=[
            {
                "key": "accounts",
                "target": "config",
                "type": "list",
                "default": [],
            }
        ],
    )
    tools = {
        "tools": [
            {
                "name": "configured_tool",
                "description": "uses a configured enum",
                "module": ".configured_pkg",
                "function": "configured_tool",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "account_name": {
                            "type": "string",
                            "enum": {"$config": "accounts"},
                        }
                    },
                    "required": ["account_name"],
                },
                "requires_confirmation": False,
                "background": True,
            }
        ]
    }
    fixture_package(
        "configured_pkg",
        manifest,
        tools,
        "def configured_tool(account_name):\n    return {'success': True}\n",
        config={"accounts": ["acct_a", "acct_b"]},
    )
    registry.reload_registry()

    specs = {s.name: s for s in toolbox.iter_specs()}
    assert specs["configured_tool"].parameters["properties"]["account_name"]["enum"] == [
        "acct_a",
        "acct_b",
    ]


def test_unconfigured_placeholder_drops_key_instead_of_crashing(fixture_package):
    manifest = _manifest(
        "unconfigured_pkg",
        provides=["unconfigured_tool"],
        config=[{"key": "accounts", "target": "config", "type": "list", "default": None}],
    )
    tools = {
        "tools": [
            {
                "name": "unconfigured_tool",
                "description": "uses a not-yet-configured enum",
                "module": ".unconfigured_pkg",
                "function": "unconfigured_tool",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "account_name": {
                            "type": "string",
                            "enum": {"$config": "accounts"},
                        }
                    },
                    "required": [],
                },
                "requires_confirmation": False,
                "background": True,
            }
        ]
    }
    fixture_package(
        "unconfigured_pkg",
        manifest,
        tools,
        "def unconfigured_tool(account_name=None):\n    return {'success': True}\n",
    )
    registry.reload_registry()

    specs = {s.name: s for s in toolbox.iter_specs()}
    assert "enum" not in specs["unconfigured_tool"].parameters["properties"]["account_name"]


def test_manifest_id_must_match_directory_name(fixture_package):
    fixture_package(
        "dir_name_pkg",
        _manifest("wrong_id"),
        _tools("mismatched_tool"),
        "def mismatched_tool():\n    return {'success': True}\n",
    )
    registry.reload_registry()

    assert not toolbox.has_tool("mismatched_tool")
    assert any("dir_name_pkg" in w for w in toolbox.load_warnings())
