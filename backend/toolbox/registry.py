import importlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MANIFEST_PATH = Path(__file__).resolve().parent / "tools.json"


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


def _load_manifest() -> dict[str, ToolEntry]:
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    tools_raw = raw.get("tools", [])
    if not isinstance(tools_raw, list):
        raise TypeError("toolbox manifest: 'tools' must be a list")
    entries: dict[str, ToolEntry] = {}
    for item in tools_raw:
        if not isinstance(item, dict):
            raise TypeError("toolbox manifest: each tool must be an object")
        spec = ToolSpec.model_validate(item)
        if spec.name in entries:
            raise ValueError(f"toolbox manifest: duplicate tool name '{spec.name}'")
        try:
            module = importlib.import_module(spec.module)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"toolbox manifest: failed to load '{spec.module}': {exc}")
        fn = getattr(module, spec.function, None)
        if not callable(fn):
            raise TypeError(
                f"toolbox manifest: {spec.module}.{spec.function} is not callable"
            )
        entries[spec.name] = ToolEntry(spec, fn)
    return entries


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


_registry: dict[str, ToolEntry] = _load_manifest()
