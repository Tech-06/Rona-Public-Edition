import importlib
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

import i18n
from toolbox import packages
from toolbox.packages import PackageLoadError, PackageManifest

MANIFEST_PATH = Path(__file__).resolve().parent / "tools.json"

logger = logging.getLogger("uvicorn.error")


class ToolSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    module: str = Field(min_length=1)
    function: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}, "required": []}
    )
    requires_confirmation: bool | dict[str, Any] = False
    background: bool = False

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        if value.get("type") != "object":
            raise ValueError("parameters schema must be {'type': 'object'}")
        return value

    @field_validator("requires_confirmation")
    @classmethod
    def validate_requires_confirmation(
        cls, value: bool | dict[str, Any]
    ) -> bool | dict[str, Any]:
        if isinstance(value, bool):
            return value
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("param"), str)
            or not value.get("param")
            or not isinstance(value.get("values"), list)
            or not value.get("values")
        ):
            raise ValueError(
                "requires_confirmation condition must be "
                "{'param': <non-empty str>, 'values': <non-empty list>}"
            )
        return value

    @model_validator(mode="after")
    def validate_condition_param_exists(self) -> "ToolSpec":
        rule = self.requires_confirmation
        if isinstance(rule, dict):
            properties = self.parameters.get("properties", {})
            if rule["param"] not in properties:
                raise ValueError(
                    f"tool '{self.name}': requires_confirmation condition references "
                    f"unknown parameter '{rule['param']}'"
                )
        return self

    @model_validator(mode="after")
    def validate_background_needs_free_confirmation(self) -> "ToolSpec":
        if self.background and self.requires_confirmation is not False:
            raise ValueError(
                f"tool '{self.name}': background tools cannot have a "
                "requires_confirmation rule (approval dialogs are impossible in the "
                "background); set requires_confirmation to false or background to false"
            )
        return self


class ToolEntry:
    def __init__(self, spec: ToolSpec, fn: Callable):
        self.spec = spec
        self.fn = fn


def _load_tool_entry(item: dict[str, Any], *, origin: str) -> tuple[str, ToolEntry] | None:
    """Validate one raw tool dict and resolve it to a callable.

    Returns ``None`` (after logging a warning) instead of raising when
    ``origin`` is a custom package -- a single broken tool must not take the
    whole registry down. Core tool errors still raise: a broken core
    manifest is a bug in the base repo, not something to silently degrade.
    """
    is_core = origin == "core"
    try:
        if not isinstance(item, dict):
            raise TypeError("each tool must be an object")
        spec = ToolSpec.model_validate(item)
        module = importlib.import_module(spec.module)
        fn = getattr(module, spec.function, None)
        if not callable(fn):
            raise TypeError(f"{spec.module}.{spec.function} is not callable")
    except Exception as exc:
        if is_core:
            raise ValueError(f"toolbox manifest: failed to load core tool: {exc}") from exc
        logger.warning(i18n.t("toolbox.log_skip_tool"), origin, exc)
        return None
    return spec.name, ToolEntry(spec, fn)


def _load_manifest() -> tuple[dict[str, ToolEntry], list[PackageManifest], list[str]]:
    # A package installed (or removed) moments ago may not be visible to the
    # import system yet -- Python's path-based finders cache directory
    # listings. reload_registry() is exactly the "created/deleted files at
    # runtime that we're about to import" case the stdlib docs tell you to
    # call this for.
    importlib.invalidate_caches()
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    tools_raw = raw.get("tools", [])
    if not isinstance(tools_raw, list):
        raise TypeError("toolbox manifest: 'tools' must be a list")

    entries: dict[str, ToolEntry] = {}
    for item in tools_raw:
        loaded = _load_tool_entry(item, origin="core")
        assert loaded is not None  # core failures raise instead of returning None
        name, entry = loaded
        if name in entries:
            raise ValueError(f"toolbox manifest: duplicate tool name '{name}'")
        entries[name] = entry

    loaded_packages: list[PackageManifest] = []
    warnings: list[str] = []
    for pkg_dir in packages.iter_installed():
        try:
            manifest = packages.load_manifest(pkg_dir)
            tools_raw = packages.load_tools_raw(pkg_dir, manifest)
        except PackageLoadError as exc:
            message = f"skipping package in {pkg_dir}: {exc}"
            logger.warning("toolbox: %s", message)
            warnings.append(message)
            continue

        package_ok = True
        package_entries: dict[str, ToolEntry] = {}
        for item in tools_raw:
            loaded = _load_tool_entry(item, origin=manifest.id)
            if loaded is None:
                package_ok = False
                continue
            name, entry = loaded
            if name in entries or name in package_entries:
                message = (
                    f"package '{manifest.id}': tool name '{name}' conflicts with an "
                    "already-loaded tool, skipping it"
                )
                logger.warning("toolbox: %s", message)
                warnings.append(message)
                package_ok = False
                continue
            package_entries[name] = entry

        entries.update(package_entries)
        loaded_packages.append(manifest)
        if not package_ok:
            warnings.append(
                f"package '{manifest.id}' loaded with some tools skipped (see log)"
            )

    return entries, loaded_packages, warnings


def has_tool(name: str) -> bool:
    return name in _registry


def get_tool(name: str) -> Callable:
    entry = _registry.get(name)
    if entry is None:
        raise KeyError(f"unknown tool: {name}")
    return entry.fn


def iter_specs() -> list[ToolSpec]:
    return [entry.spec for entry in _registry.values()]


def requires_confirmation(name: str, args: dict[str, Any] | None = None) -> bool:
    entry = _registry.get(name)
    if entry is None:
        raise KeyError(f"unknown tool: {name}")
    rule = entry.spec.requires_confirmation
    if isinstance(rule, bool):
        return rule
    if not isinstance(args, dict):
        return True
    return args.get(rule["param"]) in rule["values"]


def background_tool_names() -> set[str]:
    return {entry.spec.name for entry in _registry.values() if entry.spec.background}


def get_tool_schemas(names: set[str] | None = None) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": entry.spec.name,
                "description": entry.spec.description,
                "parameters": entry.spec.parameters,
            },
        }
        for name, entry in _registry.items()
        if names is None or name in names
    ]


def installed_packages() -> list[PackageManifest]:
    """Custom packages that loaded successfully, in load order."""
    return list(_installed_packages)


def load_warnings() -> list[str]:
    """Human-readable problems hit while loading custom packages, if any."""
    return list(_load_warnings)


def reload_registry() -> None:
    """Re-scan toolbox/tools.json and every installed package from disk.

    Called after `toolbox.manager` installs or removes a package so the
    running process picks up the change without a restart. Also used by
    tests to exercise package loading without a real process restart.
    """
    global _registry, _installed_packages, _load_warnings
    _registry, _installed_packages, _load_warnings = _load_manifest()


_registry: dict[str, ToolEntry]
_installed_packages: list[PackageManifest]
_load_warnings: list[str]
_registry, _installed_packages, _load_warnings = _load_manifest()
