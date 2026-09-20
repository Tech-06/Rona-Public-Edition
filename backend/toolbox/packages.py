"""Custom tool package support.

Rona ships a small set of *core* tools directly inside ``toolbox/tools``
(defined in ``toolbox/tools.json``). Everything else is an optional *custom
package* that a user can pull in on demand from the separate ``Rona Tools``
catalog repository and drop into ``toolbox/custom/<package_id>/``.

This module defines the on-disk package format and the pure, side-effect
-light helpers for reading it:

    toolbox/custom/<package_id>/
        manifest.json   -- PackageManifest (this file's schema)
        tools.json       -- same shape as the core tools.json ("tools": [...])
        config.json       -- optional, non-secret config values (git-ignored)
        <schema_sql file> -- optional, applied to rona.db on install
        *.py               -- the tool implementations

``toolbox.registry`` merges the core manifest with every installed package's
``tools.json`` at import time (see ``registry.reload_registry``). Installing
and removing packages (fetching them from a source, running pip installs,
prompting for config, health-checking, rolling back) is handled by
``toolbox.manager`` -- this module only knows how to read what is already on
disk.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

import i18n

logger = logging.getLogger("uvicorn.error")

# backend/toolbox/packages.py -> parents[1] == backend/
BACKEND_DIR = Path(__file__).resolve().parents[1]
CUSTOM_DIR = Path(__file__).resolve().parent / "custom"
LOCKFILE_PATH = CUSTOM_DIR / "installed.json"
# Where uninstall parks a package's user data when the user asks to keep it.
# Named with a leading dot so iter_installed() never mistakes it for a package.
PRESERVED_DIR = CUSTOM_DIR / ".preserved"
ENV_PATH = BACKEND_DIR / ".env"

_PACKAGE_ID_PATTERN = r"^[a-z][a-z0-9_]*$"


class ConfigField(BaseModel):
    """One user-configurable value a package needs after install.

    ``target`` decides where the resolved value is persisted:
      - "env": a secret/environment value, written to the backend's ``.env``
        under ``env_var`` (never stored in the package's own config.json).
      - "config": a non-secret value (e.g. a list of Google account names),
        stored in ``toolbox/custom/<id>/config.json`` under ``key``.
      - "file": a local file the user points to (e.g. a Google OAuth
        ``credentials.json``), copied into the package directory under
        ``dest_filename`` rather than stored as a value anywhere.
    """

    model_config = ConfigDict(frozen=True)

    key: str = Field(min_length=1)
    label: str = ""
    description: str = ""
    type: Literal["string", "integer", "boolean", "list"] = "string"
    target: Literal["env", "config", "file"] = "config"
    env_var: str | None = None
    dest_filename: str | None = None
    secret: bool = False
    required: bool = True
    default: Any = None

    def display_label(self) -> str:
        return self.label or self.key


class PackageAction(BaseModel):
    """A named operation a package exposes to the *operator* (not the model).

    Tools are what the model calls; actions are what a human calls -- one-off
    setup or maintenance operations that have no business sitting in the
    model's tool list: authorizing a Google account, listing or revoking those
    authorizations, re-running a migration. The manifest only declares them;
    ``toolbox.manager.run_action`` resolves and runs the handler, and
    ``rona tools run`` / the dashboard's package panel drive it.

    ``handler`` uses the same ``"<module>:<function>"`` form as
    ``health_check``, a leading ``"."`` meaning "inside this package". The
    handler is called as ``handler(config, params, state)`` and returns one of:

        {"status": "ok", "message": str, "data": {...}}
        {"status": "error", "message": str}
        {"status": "input_required", "message": str,
         "fields": [<ConfigField dict>, ...], "state": {...}}

    ``input_required`` is what makes multi-step flows (an OAuth consent round
    trip, say) work identically over a terminal and over HTTP: the caller
    collects ``fields``, then calls the same action again with those values
    and the returned ``state`` handed back verbatim. ``state`` must be JSON
    -serialisable precisely so the host never has to keep a session alive
    between the steps.

    ``params`` reuses ``ConfigField`` so one form renderer (a CLI prompt or a
    web input) serves both config and action input. ``target``, ``env_var``
    and ``dest_filename`` are meaningless for a parameter and are ignored --
    an action's inputs go to the handler, they are never persisted by the host.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, pattern=_PACKAGE_ID_PATTERN)
    label: str = ""
    description: str = ""
    handler: str = Field(min_length=1)
    params: list[ConfigField] = Field(default_factory=list)
    # Ask for confirmation before running (revokes something, deletes a file).
    destructive: bool = False
    # Never offer over HTTP. For actions that block far longer than the web
    # dashboard's proxy timeout, or that only make sense on the machine the
    # backend itself runs on (opening a local browser, for instance).
    cli_only: bool = False

    def display_label(self) -> str:
        return self.label or self.id


class PackageManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, pattern=_PACKAGE_ID_PATTERN)
    version: str = Field(min_length=1)
    kind: Literal["tool", "library"] = "tool"
    name: str = Field(min_length=1)
    description: str = ""
    provides: list[str] = Field(default_factory=list)
    requires: list[str] = Field(default_factory=list)
    python_requirements: list[str] = Field(default_factory=list)
    schema_sql: str | None = None
    config: list[ConfigField] = Field(default_factory=list)
    actions: list[PackageAction] = Field(default_factory=list)
    health_check: str | None = None
    tools_file: str = "tools.json"
    # Glob patterns, relative to the package directory, matching files the
    # *user* produced rather than the package shipped (google_auth's
    # token_<account>.json, say). Uninstall offers to preserve these instead
    # of deleting them with the rest of the package -- see manager.uninstall.
    user_data_globs: list[str] = Field(default_factory=list)

    def env_fields(self) -> list[ConfigField]:
        return [f for f in self.config if f.target == "env"]

    def config_fields(self) -> list[ConfigField]:
        return [f for f in self.config if f.target == "config"]

    def find_action(self, action_id: str) -> PackageAction | None:
        return next((a for a in self.actions if a.id == action_id), None)


class PackageLoadError(Exception):
    """Raised when a package on disk cannot be read; callers should log and skip it."""


def package_dir(package_id: str) -> Path:
    return CUSTOM_DIR / package_id


def config_path(package_id: str) -> Path:
    return package_dir(package_id) / "config.json"


def load_manifest(pkg_dir: Path) -> PackageManifest:
    """Read and validate ``manifest.json`` from a package directory."""
    manifest_path = pkg_dir / "manifest.json"
    if not manifest_path.is_file():
        raise PackageLoadError(f"{pkg_dir}: manifest.json not found")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PackageLoadError(f"{pkg_dir}: invalid manifest.json: {exc}") from exc
    try:
        manifest = PackageManifest.model_validate(raw)
    except Exception as exc:
        raise PackageLoadError(f"{pkg_dir}: invalid manifest schema: {exc}") from exc
    if manifest.id != pkg_dir.name:
        raise PackageLoadError(
            f"{pkg_dir}: manifest id '{manifest.id}' does not match "
            f"directory name '{pkg_dir.name}'"
        )
    return manifest


def read_config_file(package_id: str) -> dict[str, Any]:
    path = config_path(package_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PackageLoadError(f"{path}: invalid config.json: {exc}") from exc
    if not isinstance(data, dict):
        raise PackageLoadError(f"{path}: config.json must be a JSON object")
    return data


def write_config_file(package_id: str, values: dict[str, Any]) -> None:
    path = config_path(package_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def load_config_values(manifest: PackageManifest) -> dict[str, Any]:
    """Resolve every declared config field to its current value.

    Defaults are overlaid by the persisted config.json (for "config" target
    fields) and by the backend's .env / process environment (for "env"
    target fields). Missing required values simply come back as ``None`` --
    callers decide how to react (registry drops the placeholder, manager
    treats it as "not configured yet").
    """
    load_dotenv(ENV_PATH)
    stored = {}
    try:
        stored = read_config_file(manifest.id)
    except PackageLoadError as exc:
        logger.warning("toolbox: %s", exc)

    values: dict[str, Any] = {}
    for field in manifest.config:
        if field.target == "env":
            env_var = field.env_var or f"{manifest.id.upper()}_{field.key.upper()}"
            value = os.getenv(env_var)
            values[field.key] = value if value not in (None, "") else field.default
        elif field.target == "file":
            dest = package_dir(manifest.id) / (field.dest_filename or field.key)
            values[field.key] = str(dest) if dest.is_file() else None
        else:
            value = stored.get(field.key, field.default)
            values[field.key] = value
    return values


def resolve_placeholders(obj: Any, config_values: dict[str, Any]) -> Any:
    """Recursively replace ``{"$config": "<key>"}`` leaves with resolved values.

    Used so a tool's JSON schema (e.g. an ``enum`` of Google account names)
    can be generated from the package's own config instead of being hard
    -coded into tools.json. A reference to a key with no resolved value is
    dropped (returns ``None``, and the caller is expected to prune it) so a
    not-yet-configured package still loads instead of crashing the registry.
    """
    if isinstance(obj, dict):
        if set(obj.keys()) == {"$config"} and isinstance(obj["$config"], str):
            return config_values.get(obj["$config"])
        result: dict[str, Any] = {}
        for key, value in obj.items():
            resolved = resolve_placeholders(value, config_values)
            if resolved is None and isinstance(value, dict) and "$config" in value:
                # Unconfigured placeholder: drop the key entirely rather than
                # emit a null schema fragment.
                continue
            result[key] = resolved
        return result
    if isinstance(obj, list):
        return [
            item
            for item in (resolve_placeholders(v, config_values) for v in obj)
            if item is not None
        ]
    return obj


def load_tools_raw(pkg_dir: Path, manifest: PackageManifest) -> list[dict[str, Any]]:
    """Read a package's tools.json, resolve module paths and $config refs."""
    tools_path = pkg_dir / manifest.tools_file
    if not tools_path.is_file():
        raise PackageLoadError(f"{pkg_dir}: {manifest.tools_file} not found")
    try:
        raw = json.loads(tools_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PackageLoadError(f"{pkg_dir}: invalid {manifest.tools_file}: {exc}") from exc
    tools = raw.get("tools", [])
    if not isinstance(tools, list):
        raise PackageLoadError(f"{pkg_dir}: 'tools' must be a list")

    config_values = load_config_values(manifest)
    resolved: list[dict[str, Any]] = []
    for item in tools:
        if not isinstance(item, dict):
            raise PackageLoadError(f"{pkg_dir}: each tool must be an object")
        item = copy.deepcopy(item)
        module = item.get("module", "")
        if isinstance(module, str) and module.startswith("."):
            item["module"] = f"toolbox.custom.{manifest.id}{module}"
        item = resolve_placeholders(item, config_values)
        resolved.append(item)
    return resolved


def iter_installed() -> list[Path]:
    """Directories under toolbox/custom/ that should hold an installed package.

    Deliberately does *not* filter out directories missing a manifest.json:
    an incomplete/corrupt install should surface as a loud, logged warning
    from ``load_manifest`` rather than silently vanish from the listing.
    """
    if not CUSTOM_DIR.is_dir():
        return []
    dirs = [
        p
        for p in CUSTOM_DIR.iterdir()
        if p.is_dir() and not p.name.startswith((".", "__"))
    ]
    return sorted(dirs, key=lambda p: p.name)


def user_data_paths(manifest: PackageManifest) -> list[Path]:
    """Files inside an installed package matching its ``user_data_globs``.

    Patterns are resolved strictly inside the package directory: a pattern
    that escapes it (``../``, an absolute path) is ignored rather than
    honoured, so a manifest can never point uninstall at arbitrary files.
    """
    pkg_dir = package_dir(manifest.id)
    if not pkg_dir.is_dir():
        return []
    root = pkg_dir.resolve()
    found: list[Path] = []
    for pattern in manifest.user_data_globs:
        for path in sorted(pkg_dir.glob(pattern)):
            if not path.is_file() or path in found:
                continue
            if not path.resolve().is_relative_to(root):
                logger.warning(
                    "toolbox: package '%s': user_data_globs pattern %r escapes the "
                    "package directory, ignoring %s",
                    manifest.id,
                    pattern,
                    path,
                )
                continue
            found.append(path)
    return found


def preserved_dir(package_id: str) -> Path:
    return PRESERVED_DIR / package_id


def load_installed_manifests() -> list[PackageManifest]:
    manifests: list[PackageManifest] = []
    for pkg_dir in iter_installed():
        try:
            manifests.append(load_manifest(pkg_dir))
        except PackageLoadError as exc:
            logger.warning(i18n.t("toolbox.log_skip_package"), pkg_dir, exc)
    return manifests


def read_lockfile() -> dict[str, Any]:
    if not LOCKFILE_PATH.is_file():
        return {"packages": {}}
    try:
        data = json.loads(LOCKFILE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"packages": {}}
    if "packages" not in data or not isinstance(data["packages"], dict):
        data["packages"] = {}
    return data


def write_lockfile(data: dict[str, Any]) -> None:
    LOCKFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCKFILE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def record_install(package_id: str, version: str, source: str, installed_at: str) -> None:
    data = read_lockfile()
    data["packages"][package_id] = {
        "version": version,
        "source": source,
        "installed_at": installed_at,
    }
    write_lockfile(data)


def record_uninstall(package_id: str) -> None:
    data = read_lockfile()
    data["packages"].pop(package_id, None)
    write_lockfile(data)
