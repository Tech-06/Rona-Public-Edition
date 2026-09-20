"""Install, configure, verify and remove custom tool packages.

This is the orchestration layer between the catalog (``toolbox.sources``)
and the on-disk package format (``toolbox.packages``): it fetches a
package, checks it won't collide with anything already loaded, pip-installs
its Python requirements, moves it into ``toolbox/custom/<id>/``, applies its
``schema.sql`` if any, collects its configuration, runs its health check,
and -- if anything along the way fails or the user cancels -- rolls the
whole thing back so the repository ends up exactly as it started.

Everything here is plain, callback-driven Python with no ``input()`` calls
of its own, so it can be driven either by the CLI at the bottom of this
file (``python -m toolbox.manager ...``) or later by a graphical setup
wizard. The two callbacks an interactive caller supplies are:

    on_missing_config(staged, fields) -> {field.key: value, ...}
        Called when required config is missing (fields is the missing
        subset) or when the user chose to retry after a failed health check
        (fields is then the package's *entire* config list, so previously
        -entered-but-wrong values can be corrected).

    on_health_result(staged, result) -> "retry" | "keep" | "cancel"
        Called when a health check comes back with ok=False.

    on_plan(plan, complete) -> bool
        Called once, before anything is downloaded, when the install would
        pull in dependencies the user doesn't already have. See resolve_plan.

    on_user_data(package_id, paths) -> bool
        Called by uninstall when the package holds files the user produced
        rather than files it shipped. See uninstall.

A non-interactive caller (``--yes`` on the CLI, or the future wizard once it
has collected every answer up front) can simply omit these and pre-fill
``answers``; a missing required value or a failing health check then raises
instead of blocking on input.

Beyond install/uninstall this module also drives two things a package needs
*after* it is on disk:

  - ``configure_installed`` changes a package's configuration later, through
    exactly the same write paths install-time answers take.
  - ``run_action`` runs an operation the package declares in its manifest
    (``PackageAction``) for a human rather than for the model: authorizing an
    account, listing or revoking those authorizations. A handler may answer
    "input_required" with a JSON-serialisable ``state``, which the caller
    hands straight back on the next call -- that is what lets a multi-step
    flow such as an OAuth consent round trip work identically on a terminal
    and over HTTP, without the host holding a session open in between.
"""

from __future__ import annotations

import argparse
import getpass
import importlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import toolbox
from toolbox import db, envfile, packages, sources
from toolbox.packages import ConfigField, PackageAction, PackageManifest
from toolbox.sources import CatalogEntry, CatalogSource, SourceError

logger = logging.getLogger("uvicorn.error")

_PIP_TIMEOUT_SECONDS = 600

HealthDecision = Literal["retry", "keep", "cancel"]
ActionStatus = Literal["ok", "error", "input_required"]
OnMissingConfig = Callable[["StagedPackage", list[ConfigField]], dict[str, Any]]
OnHealthResult = Callable[["StagedPackage", "HealthResult"], HealthDecision]
# Called once, before anything is downloaded, when installing a package would
# pull in dependencies the user doesn't have yet. Returning False cancels.
OnPlan = Callable[[list["PlanEntry"], bool], bool]
# Called by uninstall when the package holds files the user produced. Returning
# True (the default when no callback is given) keeps them for a reinstall.
OnUserData = Callable[[str, list[Path]], bool]


class ManagerError(Exception):
    """Base class for every error this module raises deliberately."""


class PackageAlreadyInstalled(ManagerError):
    pass


class ToolNameConflict(ManagerError):
    pass


class DependencyCycle(ManagerError):
    pass


class InstallCancelled(ManagerError):
    pass


class ActionError(ManagerError):
    """Raised when a package action can't be resolved or run at all.

    A handler that runs and *reports* a failure comes back as an
    ActionResult with status "error" instead -- that is a normal outcome,
    not an exception.
    """


class HealthCheckFailed(ManagerError):
    def __init__(self, detail: str, staged: StagedPackage):
        super().__init__(detail)
        self.detail = detail
        self.staged = staged


@dataclass
class StagedPackage:
    manifest: PackageManifest
    pkg_dir: Path
    entry: CatalogEntry
    env_snapshot: dict[str, str | None] = dataclass_field(default_factory=dict)
    # File names a previous uninstall parked aside and this install put back.
    restored_user_data: list[str] = dataclass_field(default_factory=list)


@dataclass
class HealthResult:
    ok: bool
    detail: str


@dataclass
class ActionResult:
    """The outcome of one step of a package action (see PackageAction)."""

    status: ActionStatus
    message: str = ""
    data: dict[str, Any] = dataclass_field(default_factory=dict)
    # Only set when status == "input_required": what to ask the user for, and
    # the opaque blob to hand straight back on the follow-up call.
    fields: list[ConfigField] = dataclass_field(default_factory=list)
    state: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True)
class PlanEntry:
    """One package an install would touch, worked out from the catalog index."""

    id: str
    name: str
    version: str
    kind: str
    reason: Literal["requested", "dependency"]
    already_installed: bool


@dataclass
class UninstallResult:
    # Installed packages that declared a dependency on the removed one (only
    # non-empty when force=True was needed to get past them).
    dependents: list[str]
    # File names moved aside instead of deleted, restored on a reinstall.
    preserved: list[str]


# ---------------------------------------------------------------------------
# Read-only queries
# ---------------------------------------------------------------------------


def available(source: str = sources.DEFAULT_CATALOG_SOURCE) -> list[CatalogEntry]:
    return sources.parse_source(source).fetch_index()


def list_installed() -> list[PackageManifest]:
    return packages.load_installed_manifests()


def is_installed(package_id: str) -> bool:
    return packages.package_dir(package_id).is_dir()


# ---------------------------------------------------------------------------
# Staging: fetch + validate + pip install + place on disk + schema
# ---------------------------------------------------------------------------


def _declared_tool_names(pkg_dir: Path, manifest: PackageManifest) -> set[str]:
    raw = packages.load_tools_raw(pkg_dir, manifest)
    return {item["name"] for item in raw if isinstance(item, dict) and "name" in item}


def _pip_install(requirements: list[str]) -> None:
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", *requirements],
            check=True,
            capture_output=True,
            text=True,
            timeout=_PIP_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise ManagerError(f"pip is not available: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ManagerError(f"pip install timed out for: {', '.join(requirements)}") from exc
    except subprocess.CalledProcessError as exc:
        raise ManagerError(
            f"pip install failed for {', '.join(requirements)}:\n{exc.stderr}"
        ) from exc


def _apply_schema(schema_path: Path) -> None:
    if not schema_path.is_file():
        raise ManagerError(f"schema_sql file not found: {schema_path}")
    connection = db.connect_if_exists()
    if connection is None:
        raise ManagerError(
            f"{db.DB_PATH} not found -- run `python create_db.py` before installing "
            "a package that needs the database"
        )
    try:
        connection.executescript(schema_path.read_text(encoding="utf-8"))
        connection.commit()
    finally:
        connection.close()


def stage(entry: CatalogEntry, source_obj: CatalogSource) -> StagedPackage:
    """Fetch one package and place it at its final location, ready to be
    configured. Leaves nothing on disk if any step fails."""
    final_dir = packages.package_dir(entry.id)
    if final_dir.exists():
        raise PackageAlreadyInstalled(
            f"'{entry.id}' is already installed at {final_dir}; uninstall it first"
        )

    with tempfile.TemporaryDirectory(prefix=f"rona-stage-{entry.id}-") as tmp_name:
        staging_dir = Path(tmp_name) / entry.id
        source_obj.fetch_package(entry, staging_dir)
        manifest = packages.load_manifest(staging_dir)
        if manifest.id != entry.id:
            raise ManagerError(
                f"catalog entry id '{entry.id}' does not match its manifest id "
                f"'{manifest.id}'"
            )

        declared = _declared_tool_names(staging_dir, manifest)
        existing = {spec.name for spec in toolbox.iter_specs()}
        conflicts = declared & existing
        if conflicts:
            raise ToolNameConflict(
                f"package '{manifest.id}' provides tool(s) that already exist: "
                f"{', '.join(sorted(conflicts))}"
            )

        if manifest.python_requirements:
            _pip_install(manifest.python_requirements)

        shutil.copytree(staging_dir, final_dir)

    try:
        if manifest.schema_sql:
            _apply_schema(final_dir / manifest.schema_sql)
    except Exception:
        shutil.rmtree(final_dir, ignore_errors=True)
        raise

    restored = _restore_user_data(manifest.id, final_dir)
    return StagedPackage(
        manifest=manifest, pkg_dir=final_dir, entry=entry, restored_user_data=restored
    )


def _restore_user_data(package_id: str, pkg_dir: Path) -> list[str]:
    """Move back whatever a previous uninstall parked aside for this package.

    Deliberately refuses to overwrite a file the package itself ships: if the
    two ever collide the package's own copy wins and the parked one is left
    where it is, so nothing the user produced is destroyed silently.
    """
    parked = packages.preserved_dir(package_id)
    if not parked.is_dir():
        return []
    restored: list[str] = []
    for path in sorted(parked.iterdir()):
        if not path.is_file():
            continue
        dest = pkg_dir / path.name
        if dest.exists():
            logger.warning(
                "toolbox: package '%s' now ships %s, leaving the preserved copy in %s",
                package_id,
                path.name,
                parked,
            )
            continue
        shutil.move(str(path), str(dest))
        restored.append(path.name)
    if not any(parked.iterdir()):
        parked.rmdir()
        if parked.parent.is_dir() and not any(parked.parent.iterdir()):
            parked.parent.rmdir()
    return restored


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _snapshot_env_keys(keys) -> dict[str, str | None]:
    current = envfile.read_env_file(packages.ENV_PATH)
    return {key: current.get(key) for key in keys}


def _apply_file_field(staged: StagedPackage, field: ConfigField, source_value: Any) -> None:
    source = Path(str(source_value)).expanduser()
    if not source.is_file():
        raise ManagerError(f"'{staged.manifest.id}.{field.key}': file not found: {source}")
    dest = staged.pkg_dir / (field.dest_filename or field.key)
    if source.resolve() == dest.resolve():
        # Re-applying config for an already-installed package: the file is
        # already where it belongs, so there is nothing to copy (and copying
        # a file onto itself would raise).
        return
    shutil.copy2(source, dest)


def apply_config(staged: StagedPackage, answers: dict[str, Any]) -> None:
    """Validate and persist every declared config field for a staged package.

    All-or-nothing: if a required field is missing, nothing is written.
    """
    manifest = staged.manifest
    missing = [f.key for f in manifest.config if f.required and answers.get(f.key) in (None, "")]
    if missing:
        raise ManagerError(
            f"missing required config for '{manifest.id}': {', '.join(missing)}"
        )

    env_updates: dict[str, str] = {}
    config_updates: dict[str, Any] = {}
    file_updates: list[tuple[ConfigField, Any]] = []
    for cfg_field in manifest.config:
        value = answers.get(cfg_field.key, cfg_field.default)
        if value is None:
            continue
        if cfg_field.target == "env":
            env_var = cfg_field.env_var or f"{manifest.id.upper()}_{cfg_field.key.upper()}"
            env_updates[env_var] = str(value)
        elif cfg_field.target == "file":
            file_updates.append((cfg_field, value))
        else:
            config_updates[cfg_field.key] = value

    # Apply file copies first -- if a source path is bad we want to fail
    # before touching .env or config.json.
    for cfg_field, value in file_updates:
        _apply_file_field(staged, cfg_field, value)

    if env_updates:
        staged.env_snapshot.update(_snapshot_env_keys(env_updates.keys()))
        envfile.write_env_updates(packages.ENV_PATH, env_updates)
        for key, value in env_updates.items():
            os.environ[key] = value  # visible immediately in this process

    if config_updates:
        existing = packages.read_config_file(manifest.id)
        existing.update(config_updates)
        packages.write_config_file(manifest.id, existing)


def _restore_env(snapshot: dict[str, str | None]) -> None:
    restore = {k: v for k, v in snapshot.items() if v is not None}
    remove = [k for k, v in snapshot.items() if v is None]
    if restore:
        envfile.write_env_updates(packages.ENV_PATH, restore)
    if remove:
        envfile.remove_env_keys(packages.ENV_PATH, remove)
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------


def run_health_check(manifest: PackageManifest) -> HealthResult:
    if not manifest.health_check:
        return HealthResult(True, "no health check declared")
    module_part, sep, func_name = manifest.health_check.partition(":")
    if not sep or not func_name:
        return HealthResult(False, f"invalid health_check spec: {manifest.health_check!r}")
    module_name = (
        f"toolbox.custom.{manifest.id}{module_part}"
        if module_part.startswith(".")
        else module_part
    )
    try:
        module = importlib.import_module(module_name)
        fn = getattr(module, func_name)
        config_values = packages.load_config_values(manifest)
        result = fn(config_values)
    except Exception as exc:  # noqa: BLE001
        return HealthResult(False, f"health check raised: {exc}")
    if not isinstance(result, dict):
        return HealthResult(False, "health check did not return a dict")
    return HealthResult(bool(result.get("ok")), str(result.get("detail", "")))


def verify_installed(package_id: str) -> HealthResult:
    """Re-run an already-installed package's health check on demand."""
    return run_health_check(_installed_manifest(package_id))


def _installed_manifest(package_id: str) -> PackageManifest:
    pkg_dir = packages.package_dir(package_id)
    if not pkg_dir.is_dir():
        raise ManagerError(f"'{package_id}' is not installed")
    return packages.load_manifest(pkg_dir)


# ---------------------------------------------------------------------------
# Post-install configuration
# ---------------------------------------------------------------------------


def configure_installed(package_id: str, answers: dict[str, Any]) -> HealthResult:
    """Change an already-installed package's config, then re-check its health.

    Goes through the very same apply_config() the installer uses, so .env
    secrets, config.json values and copied files all land where install-time
    answers would have put them -- callers (``rona tools config``, the
    dashboard) never have to know the difference. Fields not mentioned in
    ``answers`` keep whatever value they already have.
    """
    manifest = _installed_manifest(package_id)
    unknown = set(answers) - {f.key for f in manifest.config}
    if unknown:
        raise ManagerError(
            f"package '{package_id}' has no config field(s): {', '.join(sorted(unknown))}"
        )

    current = packages.load_config_values(manifest)
    merged = {k: v for k, v in current.items() if v not in (None, "")}
    merged.update(answers)

    staged = StagedPackage(
        manifest=manifest,
        pkg_dir=packages.package_dir(package_id),
        entry=CatalogEntry(
            id=manifest.id,
            version=manifest.version,
            name=manifest.name,
            description=manifest.description,
            path="",
            kind=manifest.kind,
        ),
    )
    apply_config(staged, merged)
    toolbox.reload_registry()
    return run_health_check(manifest)


# ---------------------------------------------------------------------------
# Package actions
# ---------------------------------------------------------------------------


def _resolve_handler(manifest: PackageManifest, spec: str) -> Callable[..., Any]:
    """Turn a "<module>:<function>" handler spec into a callable.

    Same resolution rules as health_check: a leading "." on the module part
    means "inside this package".
    """
    module_part, sep, func_name = spec.partition(":")
    if not sep or not func_name:
        raise ActionError(f"invalid handler spec: {spec!r}")
    module_name = (
        f"toolbox.custom.{manifest.id}{module_part}"
        if module_part.startswith(".")
        else module_part
    )
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        raise ActionError(f"could not import {module_name!r}: {exc}") from exc
    fn = getattr(module, func_name, None)
    if not callable(fn):
        raise ActionError(f"{spec!r} is not a callable")
    return fn


def _is_json_safe(value: Any) -> bool:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return False
    return True


def _coerce_action_result(raw: Any) -> ActionResult:
    """Validate what a handler returned.

    Anything malformed becomes a plain "error" result rather than reaching
    the CLI or the HTTP layer as an exception -- a third-party package's bug
    should read as a failed action, not a crashed backend.
    """
    if not isinstance(raw, dict):
        return ActionResult("error", "action did not return a dict")
    status = raw.get("status")
    if status not in ("ok", "error", "input_required"):
        return ActionResult("error", f"action returned an unknown status: {status!r}")
    message = str(raw.get("message", ""))

    if status == "input_required":
        try:
            fields = [ConfigField.model_validate(f) for f in raw.get("fields") or []]
        except Exception as exc:  # noqa: BLE001
            return ActionResult("error", f"action returned invalid input fields: {exc}")
        if not fields:
            return ActionResult("error", "action asked for input but declared no fields")
        state = raw.get("state")
        if state is not None and not isinstance(state, dict):
            return ActionResult("error", "action returned a non-object state")
        if not _is_json_safe(state):
            # Handing state back to the caller is the whole reason the host
            # keeps no session between steps; state that can't be serialised
            # would work in a terminal and then break over HTTP.
            return ActionResult(
                "error", "action returned a state that is not JSON-serialisable"
            )
        return ActionResult(status, message, fields=fields, state=state)

    data = raw.get("data") or {}
    if not isinstance(data, dict):
        data = {"value": data}
    if not _is_json_safe(data):
        return ActionResult("error", "action returned data that is not JSON-serialisable")
    return ActionResult(status, message, data=data)


def run_action(
    package_id: str,
    action_id: str,
    params: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
    *,
    allow_cli_only: bool = True,
) -> ActionResult:
    """Run one step of a package's declared action.

    A handler returning "input_required" hasn't failed -- it needs more from
    the user. Collect the fields it named and call this again with those
    values plus the ``state`` it handed back, unchanged. A non-None ``state``
    is also how this knows it is on a follow-up step, and so stops
    re-validating the action's own declared parameters (already supplied on
    the first call).

    ``allow_cli_only=False`` is what the HTTP layer passes: actions marked
    cli_only either block for far longer than a request may take, or only
    make sense on the machine the backend itself runs on.
    """
    manifest = _installed_manifest(package_id)
    action = manifest.find_action(action_id)
    if action is None:
        known = ", ".join(a.id for a in manifest.actions) or "none"
        raise ManagerError(
            f"package '{package_id}' has no action '{action_id}' (available: {known})"
        )
    if action.cli_only and not allow_cli_only:
        raise ManagerError(f"action '{package_id}.{action_id}' can only be run from a terminal")

    supplied = dict(params or {})
    if state is None:
        missing = [
            f.key for f in action.params if f.required and supplied.get(f.key) in (None, "")
        ]
        if missing:
            raise ManagerError(f"action '{package_id}.{action_id}' needs: {', '.join(missing)}")

    handler = _resolve_handler(manifest, action.handler)
    # Config is re-read on every step so a change made between two steps of a
    # multi-step action is visible to the next one.
    config_values = packages.load_config_values(manifest)
    try:
        raw = handler(config_values, supplied, state)
    except Exception as exc:  # noqa: BLE001
        return ActionResult("error", f"action raised: {exc}")

    result = _coerce_action_result(raw)
    if result.ok:
        # An action may well have changed what the tools look like -- a newly
        # authorized account showing up in a $config enum, say.
        toolbox.reload_registry()
    return result


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


def rollback_staged(staged: StagedPackage) -> None:
    shutil.rmtree(staged.pkg_dir, ignore_errors=True)
    if staged.env_snapshot:
        _restore_env(staged.env_snapshot)
    packages.record_uninstall(staged.manifest.id)
    toolbox.reload_registry()


def finalize(staged: StagedPackage, source_spec: str) -> None:
    packages.record_install(
        staged.manifest.id,
        staged.manifest.version,
        source_spec,
        datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Install orchestration
# ---------------------------------------------------------------------------


def _configure_and_verify_one(
    staged: StagedPackage,
    answers: dict[str, dict[str, Any]],
    *,
    on_missing_config: OnMissingConfig | None,
    on_health_result: OnHealthResult | None,
    keep_on_health_failure: bool,
) -> HealthResult:
    pkg_answers = dict(answers.get(staged.manifest.id, {}))
    while True:
        missing = [
            f
            for f in staged.manifest.config
            if f.required and pkg_answers.get(f.key) in (None, "")
        ]
        if missing:
            if on_missing_config is None:
                raise ManagerError(
                    f"package '{staged.manifest.id}' needs config: "
                    + ", ".join(f.key for f in missing)
                )
            pkg_answers.update(on_missing_config(staged, missing))
            continue

        apply_config(staged, pkg_answers)
        toolbox.reload_registry()
        result = run_health_check(staged.manifest)
        if result.ok or keep_on_health_failure:
            return result
        if on_health_result is None:
            raise HealthCheckFailed(result.detail, staged)
        decision = on_health_result(staged, result)
        if decision == "keep":
            return result
        if decision == "cancel":
            raise InstallCancelled(
                f"installation of '{staged.manifest.id}' cancelled after failed health check"
            )
        if decision == "retry":
            if on_missing_config is None:
                # A caller that supplied on_health_result but not
                # on_missing_config has no way to collect corrected values;
                # treat the retry as unsatisfiable rather than crashing.
                raise HealthCheckFailed(result.detail, staged)
            pkg_answers.update(on_missing_config(staged, list(staged.manifest.config)))
            continue
        raise ManagerError(f"unknown health-check decision: {decision!r}")


def _install_recursive(
    package_id: str,
    source_obj: CatalogSource,
    staged_in_this_run: list[StagedPackage],
    answers: dict[str, dict[str, Any]],
    *,
    in_progress: set[str],
    on_missing_config: OnMissingConfig | None,
    on_health_result: OnHealthResult | None,
    keep_on_health_failure: bool,
) -> None:
    if package_id in in_progress:
        # Must be checked before the "already done" shortcuts below: a
        # package that is still being staged (its own `requires` are being
        # walked right now) is by definition not finished yet, even though
        # it is already sitting in staged_in_this_run.
        raise DependencyCycle(f"circular 'requires' dependency involving '{package_id}'")
    if any(sp.manifest.id == package_id for sp in staged_in_this_run):
        return
    if is_installed(package_id):
        return
    in_progress.add(package_id)

    entry = source_obj.find_entry(package_id)
    staged = stage(entry, source_obj)
    staged_in_this_run.append(staged)

    for dep_id in staged.manifest.requires:
        _install_recursive(
            dep_id,
            source_obj,
            staged_in_this_run,
            answers,
            in_progress=in_progress,
            on_missing_config=on_missing_config,
            on_health_result=on_health_result,
            keep_on_health_failure=keep_on_health_failure,
        )

    _configure_and_verify_one(
        staged,
        answers,
        on_missing_config=on_missing_config,
        on_health_result=on_health_result,
        keep_on_health_failure=keep_on_health_failure,
    )
    in_progress.discard(package_id)


def resolve_plan(
    package_id: str, source_obj: CatalogSource
) -> tuple[list[PlanEntry], bool]:
    """What installing ``package_id`` would pull in, from the index alone.

    Nothing is downloaded: this reads the dependency graph straight out of
    the catalog's index.json, which is the only way to tell a user what is
    about to happen *before* it happens.

    Returns the entries in install order (dependencies first) plus a
    ``complete`` flag. ``complete`` is False when something on the path did
    not declare ``requires`` in the index at all -- an older catalog. The plan
    is then a lower bound, and callers must say so rather than present it as
    the whole story.
    """
    entries = {entry.id: entry for entry in source_obj.fetch_index()}
    plan: list[PlanEntry] = []
    seen: set[str] = set()
    complete = True

    def walk(pkg_id: str, reason: str, chain: tuple[str, ...]) -> None:
        nonlocal complete
        if pkg_id in chain:
            raise DependencyCycle(f"circular 'requires' dependency involving '{pkg_id}'")
        if pkg_id in seen:
            return
        entry = entries.get(pkg_id)
        if entry is None:
            where = f" (required by '{chain[-1]}')" if chain else ""
            raise SourceError(f"package '{pkg_id}' not found in catalog{where}")
        seen.add(pkg_id)
        if entry.requires is None:
            complete = False
        for dep_id in entry.requires or ():
            walk(dep_id, "dependency", chain + (pkg_id,))
        plan.append(
            PlanEntry(
                id=entry.id,
                name=entry.name,
                version=entry.version,
                kind=entry.kind,
                reason=reason,
                already_installed=is_installed(entry.id),
            )
        )

    walk(package_id, "requested", ())
    return plan, complete


def install(
    package_id: str,
    *,
    source: str = sources.DEFAULT_CATALOG_SOURCE,
    answers: dict[str, dict[str, Any]] | None = None,
    on_missing_config: OnMissingConfig | None = None,
    on_health_result: OnHealthResult | None = None,
    on_plan: OnPlan | None = None,
    keep_on_health_failure: bool = False,
) -> list[StagedPackage]:
    """Install ``package_id`` and any not-yet-installed dependencies.

    Returns the list of packages staged during this call (in install
    order). On any failure or cancellation, every one of them is rolled
    back before the exception propagates -- the repository ends up exactly
    as it was before the call.

    ``on_plan``, when given, is consulted *before anything is downloaded* and
    only when the install would actually bring in a dependency the user does
    not already have; returning False cancels. A catalog that doesn't publish
    dependency metadata therefore never prompts -- the install simply behaves
    as it always did and resolves requires from each manifest as it goes.
    """
    source_obj = sources.parse_source(source)

    if on_plan is not None:
        plan, complete = resolve_plan(package_id, source_obj)
        extra = [e for e in plan if e.reason == "dependency" and not e.already_installed]
        if extra and not on_plan(plan, complete):
            raise InstallCancelled(f"installation of '{package_id}' cancelled")

    staged_in_this_run: list[StagedPackage] = []
    try:
        _install_recursive(
            package_id,
            source_obj,
            staged_in_this_run,
            answers or {},
            in_progress=set(),
            on_missing_config=on_missing_config,
            on_health_result=on_health_result,
            keep_on_health_failure=keep_on_health_failure,
        )
    except Exception:
        for staged in reversed(staged_in_this_run):
            rollback_staged(staged)
        raise

    for staged in staged_in_this_run:
        finalize(staged, source)
    return staged_in_this_run


def uninstall(
    package_id: str,
    *,
    force: bool = False,
    purge: bool = False,
    on_user_data: OnUserData | None = None,
) -> UninstallResult:
    """Remove an installed package.

    Files matching the manifest's ``user_data_globs`` are things the *user*
    produced, not things the package shipped -- a Google account's OAuth
    token, say. Deleting those with the package means re-doing work that may
    not even be possible from the machine at hand, so they are kept by
    default: moved into ``toolbox/custom/.preserved/<id>/`` and put back
    automatically if the package is ever reinstalled. ``purge=True`` deletes
    them outright; ``on_user_data`` lets an interactive caller ask first.
    """
    pkg_dir = packages.package_dir(package_id)
    if not pkg_dir.is_dir():
        raise ManagerError(f"'{package_id}' is not installed")

    dependents = [
        m.id
        for m in packages.load_installed_manifests()
        if m.id != package_id and package_id in m.requires
    ]
    if dependents and not force:
        raise ManagerError(
            f"cannot uninstall '{package_id}': required by "
            f"{', '.join(sorted(dependents))} (use force=True / --force to proceed anyway)"
        )

    preserved: list[str] = []
    if not purge:
        try:
            manifest = packages.load_manifest(pkg_dir)
        except packages.PackageLoadError:
            # A corrupt package still has to be removable; it just can't tell
            # us which of its files are user data.
            manifest = None
        user_data = packages.user_data_paths(manifest) if manifest else []
        if user_data and (on_user_data is None or on_user_data(package_id, list(user_data))):
            parked = packages.preserved_dir(package_id)
            parked.mkdir(parents=True, exist_ok=True)
            for path in user_data:
                dest = parked / path.name
                if dest.exists():
                    dest.unlink()
                shutil.move(str(path), str(dest))
                preserved.append(path.name)

    shutil.rmtree(pkg_dir)
    packages.record_uninstall(package_id)
    toolbox.reload_registry()
    return UninstallResult(dependents=dependents, preserved=preserved)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _coerce_cli_value(cfg_field: ConfigField, raw: str) -> Any:
    if cfg_field.type == "list":
        return [item.strip() for item in raw.split(",") if item.strip()]
    if cfg_field.type == "integer":
        return int(raw)
    if cfg_field.type == "boolean":
        return raw.strip().lower() in ("1", "true", "yes", "y", "on")
    return raw


def _prompt_for_fields(staged: StagedPackage, fields: list[ConfigField]) -> dict[str, Any]:
    return _prompt_fields(fields, header=f"Configuration for '{staged.manifest.id}':")


def _prompt_fields(fields: list[ConfigField], *, header: str | None = None) -> dict[str, Any]:
    """Ask for each field on the terminal. Shared by install-time config, post
    -install config and an action's parameters -- one prompt style everywhere."""
    if header:
        print(f"\n{header}")
    answers: dict[str, Any] = {}
    for cfg_field in fields:
        prompt = f"  {cfg_field.display_label()}"
        if cfg_field.description:
            prompt += f" ({cfg_field.description})"
        prompt += ": "
        while True:
            raw = (
                getpass.getpass(prompt)
                if cfg_field.secret
                else input(prompt)
            )
            if not raw and not cfg_field.required:
                break
            if not raw:
                print("  this value is required.")
                continue
            try:
                answers[cfg_field.key] = _coerce_cli_value(cfg_field, raw)
            except ValueError:
                print(f"  invalid {cfg_field.type} value, try again.")
                continue
            break
    return answers


def _prompt_config_edit(
    manifest: PackageManifest, current: dict[str, Any]
) -> dict[str, Any]:
    """Walk every config field showing its current value; blank keeps it.

    The same "blank keeps it, secrets are masked" contract `rona edit model`
    uses, so a secret never has to be typed on a command line to change one
    of its neighbours.
    """
    print(f"\nConfiguration for '{manifest.id}' (blank keeps the current value):")
    answers: dict[str, Any] = {}
    for cfg_field in manifest.config:
        value = current.get(cfg_field.key)
        if value in (None, ""):
            shown = "not set"
        elif cfg_field.secret:
            shown = "***"
        else:
            shown = value
        prompt = f"  {cfg_field.display_label()}"
        if cfg_field.description:
            prompt += f" ({cfg_field.description})"
        prompt += f" [{shown}]: "
        while True:
            raw = getpass.getpass(prompt) if cfg_field.secret else input(prompt)
            if not raw:
                break
            try:
                answers[cfg_field.key] = _coerce_cli_value(cfg_field, raw)
            except ValueError:
                print(f"  invalid {cfg_field.type} value, try again.")
                continue
            break
    return answers


def _prompt_plan(plan: list[PlanEntry], complete: bool) -> bool:
    requested = next(e for e in plan if e.reason == "requested")
    extra = [e for e in plan if e.reason == "dependency" and not e.already_installed]
    print(f"\n'{requested.id}' also needs:")
    for entry in extra:
        print(f"  {entry.id}  {entry.version}  {entry.name}")
    if not complete:
        print("  (the catalog doesn't list every dependency, so there may be more)")
    print("These will be installed and configured first.")
    while True:
        choice = input("  Continue? [y/N]: ").strip().lower()
        if choice in ("y", "yes"):
            return True
        if choice in ("", "n", "no"):
            return False
        print("  please answer y or n.")


def _prompt_user_data(package_id: str, paths: list[Path]) -> bool:
    print(f"\n'{package_id}' holds {len(paths)} file(s) you created:")
    for path in paths:
        print(f"  {path.name}")
    print("Keeping them means a later reinstall picks up where you left off.")
    while True:
        choice = input("  Keep them? [Y/n]: ").strip().lower()
        if choice in ("", "y", "yes"):
            return True
        if choice in ("n", "no"):
            return False
        print("  please answer y or n.")


def _prompt_health_decision(staged: StagedPackage, result: HealthResult) -> HealthDecision:
    print(f"\nHealth check for '{staged.manifest.id}' failed: {result.detail}")
    while True:
        choice = input("  [f]ix values / [k]eep anyway / [c]ancel: ").strip().lower()
        if choice in ("f", "fix"):
            return "retry"
        if choice in ("k", "keep"):
            return "keep"
        if choice in ("c", "cancel"):
            return "cancel"
        print("  please answer f, k or c.")


def config_field_payload(
    cfg_field: ConfigField, values: dict[str, Any] | None = None
) -> dict[str, Any]:
    """JSON view of one config field, for the CLI and the dashboard alike.

    A secret's value is never included -- only whether one is set. Callers
    that render a form need the metadata; nobody needs the secret read back.
    """
    value = (values or {}).get(cfg_field.key)
    is_set = value not in (None, "")
    payload = {
        "key": cfg_field.key,
        "label": cfg_field.display_label(),
        "description": cfg_field.description,
        "type": cfg_field.type,
        "target": cfg_field.target,
        "secret": cfg_field.secret,
        "required": cfg_field.required,
        "set": is_set,
    }
    if values is not None:
        payload["value"] = None if cfg_field.secret else value
    return payload


def action_payload(action: PackageAction) -> dict[str, Any]:
    return {
        "id": action.id,
        "label": action.display_label(),
        "description": action.description,
        "destructive": action.destructive,
        "cli_only": action.cli_only,
        "params": [config_field_payload(p) for p in action.params],
    }


def _parse_set_args(pairs: list[str], default_package_id: str) -> dict[str, dict[str, Any]]:
    answers: dict[str, dict[str, Any]] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ManagerError(f"invalid --set value {pair!r}, expected key=value")
        key, _, value = pair.partition("=")
        key = key.strip()
        if "." in key:
            pkg_id, _, field_key = key.partition(".")
        else:
            pkg_id, field_key = default_package_id, key
        answers.setdefault(pkg_id, {})[field_key] = value
    return answers


def _cli_install(args: argparse.Namespace) -> int:
    raw_answers = _parse_set_args(args.set or [], args.package_id)
    # CLI values arrive as strings; coerce them once we know each field's
    # declared type (done lazily inside the missing-config callback so we
    # only need the manifest, not a second pass over raw_answers here).

    def on_missing_config(staged: StagedPackage, fields: list[ConfigField]) -> dict[str, Any]:
        pkg_id = staged.manifest.id
        pre_supplied = raw_answers.get(pkg_id, {})
        result: dict[str, Any] = {}
        still_missing = []
        for cfg_field in fields:
            if cfg_field.key in pre_supplied:
                raw = pre_supplied.pop(cfg_field.key)
                result[cfg_field.key] = (
                    raw if not isinstance(raw, str) else _coerce_cli_value(cfg_field, raw)
                )
            else:
                still_missing.append(cfg_field)
        if still_missing:
            if args.yes:
                names = ", ".join(f"{pkg_id}.{f.key}" for f in still_missing)
                raise ManagerError(f"missing required config (use --set): {names}")
            result.update(_prompt_for_fields(staged, still_missing))
        return result

    on_health_result = None if args.yes else _prompt_health_decision

    try:
        staged = install(
            args.package_id,
            source=args.source,
            answers={pkg_id: dict(vals) for pkg_id, vals in raw_answers.items()},
            on_missing_config=on_missing_config,
            on_health_result=on_health_result,
            on_plan=None if args.yes else _prompt_plan,
            keep_on_health_failure=args.keep_on_health_failure,
        )
    # SourceError and PackageLoadError are not ManagerError subclasses: an
    # unreachable catalog or a malformed manifest used to escape as a raw
    # traceback here, which the CLI then reported as "no output from the
    # manager" rather than the real reason.
    except (ManagerError, SourceError, packages.PackageLoadError) as exc:
        _emit(args, {"ok": False, "error": str(exc)})
        return 1

    payload: dict[str, Any] = {
        "ok": True,
        "installed": [sp.manifest.id for sp in staged],
        "note": "restart the backend for it to pick up the new tool(s)",
    }
    restored = sorted({name for sp in staged for name in sp.restored_user_data})
    if restored:
        payload["restored"] = restored
    _emit(args, payload)
    return 0


def _cli_uninstall(args: argparse.Namespace) -> int:
    try:
        result = uninstall(
            args.package_id,
            force=args.force,
            purge=args.purge,
            # Without --yes and without --purge the user is asked; with --yes
            # the default (keep) applies silently, because losing work is the
            # worse of the two mistakes to make unattended.
            on_user_data=None if (args.yes or args.purge) else _prompt_user_data,
        )
    except (ManagerError, packages.PackageLoadError) as exc:
        _emit(args, {"ok": False, "error": str(exc)})
        return 1
    _emit(
        args,
        {
            "ok": True,
            "removed": args.package_id,
            "broken_dependents": result.dependents,
            "preserved": result.preserved,
        },
    )
    return 0


def _cli_available(args: argparse.Namespace) -> int:
    try:
        entries = available(args.source)
    except SourceError as exc:
        _emit(args, {"ok": False, "error": str(exc)})
        return 1
    _emit(
        args,
        {
            "ok": True,
            "packages": [
                {
                    "id": e.id,
                    "version": e.version,
                    "name": e.name,
                    "description": e.description,
                    "kind": e.kind,
                    # null (not []) when the catalog doesn't publish
                    # dependencies -- "unknown" is not "none".
                    "requires": list(e.requires) if e.requires is not None else None,
                    "installed": is_installed(e.id),
                }
                for e in entries
            ],
        },
    )
    return 0


def _cli_installed(args: argparse.Namespace) -> int:
    manifests = list_installed()
    _emit(
        args,
        {
            "ok": True,
            "packages": [
                {"id": m.id, "version": m.version, "name": m.name, "kind": m.kind}
                for m in manifests
            ],
        },
    )
    return 0


def _cli_verify(args: argparse.Namespace) -> int:
    try:
        result = verify_installed(args.package_id)
    except ManagerError as exc:
        _emit(args, {"ok": False, "error": str(exc)})
        return 1
    payload = {"ok": result.ok, "detail": result.detail}
    if not result.ok:
        # _emit reports payload["error"] when ok is false; without this the
        # one thing the user needs -- why it's unhealthy -- goes unprinted.
        payload["error"] = result.detail
    _emit(args, payload)
    return 0 if result.ok else 1


def _cli_config(args: argparse.Namespace) -> int:
    try:
        manifest = _installed_manifest(args.package_id)
        if args.set or args.edit:
            current = packages.load_config_values(manifest)
            answers: dict[str, Any] = {}
            by_key = {f.key: f for f in manifest.config}
            raw = _parse_set_args(args.set or [], args.package_id).get(args.package_id, {})
            unknown = set(raw) - set(by_key)
            if unknown:
                raise ManagerError(
                    f"package '{args.package_id}' has no config field(s): "
                    f"{', '.join(sorted(unknown))}"
                )
            for key, value in raw.items():
                answers[key] = _coerce_cli_value(by_key[key], value)
            if args.edit:
                answers.update(_prompt_config_edit(manifest, {**current, **answers}))
            if not answers:
                raise ManagerError("nothing to change")
            result = configure_installed(args.package_id, answers)
            _emit(
                args,
                {
                    "ok": True,
                    "package": args.package_id,
                    "changed": sorted(answers),
                    "health_ok": result.ok,
                    "detail": result.detail,
                    "note": "restart the backend for the change to take effect",
                },
            )
            return 0

        values = packages.load_config_values(manifest)
        fields = [config_field_payload(f, values) for f in manifest.config]
    except (ManagerError, packages.PackageLoadError) as exc:
        _emit(args, {"ok": False, "error": str(exc)})
        return 1

    if args.json:
        _emit(args, {"ok": True, "package": args.package_id, "fields": fields})
        return 0
    if not fields:
        print(f"'{args.package_id}' has no configuration.")
        return 0
    for field in fields:
        shown = "***" if field["secret"] and field["set"] else field.get("value")
        if shown in (None, ""):
            shown = "(not set)"
        print(f"{field['key']}: {shown}")
    return 0


def _cli_actions(args: argparse.Namespace) -> int:
    try:
        manifest = _installed_manifest(args.package_id)
        actions = [action_payload(a) for a in manifest.actions]
    except (ManagerError, packages.PackageLoadError) as exc:
        _emit(args, {"ok": False, "error": str(exc)})
        return 1

    if args.json:
        _emit(args, {"ok": True, "package": args.package_id, "actions": actions})
        return 0
    if not actions:
        print(f"'{args.package_id}' exposes no actions.")
        return 0
    for action in actions:
        flags = []
        if action["destructive"]:
            flags.append("destructive")
        if action["cli_only"]:
            flags.append("terminal only")
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        print(f"{action['id']}  {action['label']}{suffix}")
        if action["description"]:
            print(f"    {action['description']}")
    return 0


def _cli_run(args: argparse.Namespace) -> int:
    try:
        manifest = _installed_manifest(args.package_id)
        action = manifest.find_action(args.action_id)
        if action is None:
            known = ", ".join(a.id for a in manifest.actions) or "none"
            raise ManagerError(
                f"package '{args.package_id}' has no action '{args.action_id}' "
                f"(available: {known})"
            )

        raw = _parse_set_args(args.set or [], args.package_id).get(args.package_id, {})
        params: dict[str, Any] = {}
        still_missing: list[ConfigField] = []
        for param in action.params:
            if param.key in raw:
                params[param.key] = _coerce_cli_value(param, raw[param.key])
            elif param.required:
                still_missing.append(param)
        if still_missing:
            if args.yes:
                names = ", ".join(f.key for f in still_missing)
                raise ManagerError(f"missing required parameter(s) (use --set): {names}")
            params.update(
                _prompt_fields(still_missing, header=f"Parameters for '{action.id}':")
            )

        state: dict[str, Any] | None = None
        while True:
            result = run_action(args.package_id, args.action_id, params, state)
            if result.status != "input_required":
                break
            if args.yes:
                raise ManagerError(
                    f"action '{args.action_id}' needs interactive input; re-run without --yes"
                )
            if result.message:
                print(f"\n{result.message}")
            params = _prompt_fields(result.fields)
            state = result.state
    except (ManagerError, packages.PackageLoadError) as exc:
        _emit(args, {"ok": False, "error": str(exc)})
        return 1

    payload: dict[str, Any] = {"ok": result.ok, "status": result.status}
    if result.ok:
        payload["message"] = result.message
        if result.data:
            payload["data"] = result.data
    else:
        payload["error"] = result.message
    _emit(args, payload)
    return 0 if result.ok else 1


def _emit(args: argparse.Namespace, payload: dict[str, Any]) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False))
        return
    if payload.get("ok"):
        for key, value in payload.items():
            if key == "ok":
                continue
            print(f"{key}: {value}")
    else:
        print(f"error: {payload.get('error')}", file=sys.stderr)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m toolbox.manager")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    p_install = sub.add_parser("install", help="install a package and its dependencies")
    p_install.add_argument("package_id")
    p_install.add_argument("--source", default=sources.DEFAULT_CATALOG_SOURCE)
    p_install.add_argument(
        "--set",
        action="append",
        metavar="[pkg.]key=value",
        help="pre-supply a config value; repeatable",
    )
    p_install.add_argument(
        "--yes", action="store_true", help="never prompt; fail if config is missing"
    )
    p_install.add_argument(
        "--keep-on-health-failure",
        action="store_true",
        help="install even if the health check fails, instead of asking/rolling back",
    )
    p_install.set_defaults(func=_cli_install)

    p_uninstall = sub.add_parser("uninstall", help="remove an installed package")
    p_uninstall.add_argument("package_id")
    p_uninstall.add_argument(
        "--force", action="store_true", help="uninstall even if other packages depend on it"
    )
    p_uninstall.add_argument(
        "--purge",
        action="store_true",
        help="also delete files you created (tokens etc.) instead of keeping them",
    )
    p_uninstall.add_argument(
        "--yes", action="store_true", help="never prompt; keeps your files"
    )
    p_uninstall.set_defaults(func=_cli_uninstall)

    p_available = sub.add_parser("available", help="list packages in the catalog")
    p_available.add_argument("--source", default=sources.DEFAULT_CATALOG_SOURCE)
    p_available.set_defaults(func=_cli_available)

    p_installed = sub.add_parser("installed", help="list installed custom packages")
    p_installed.set_defaults(func=_cli_installed)

    p_verify = sub.add_parser("verify", help="re-run an installed package's health check")
    p_verify.add_argument("package_id")
    p_verify.set_defaults(func=_cli_verify)

    p_config = sub.add_parser(
        "config", help="show or change an installed package's configuration"
    )
    p_config.add_argument("package_id")
    p_config.add_argument(
        "--set", action="append", metavar="key=value", help="set one value; repeatable"
    )
    p_config.add_argument(
        "--edit",
        action="store_true",
        help="prompt for every field (blank keeps the current value)",
    )
    p_config.set_defaults(func=_cli_config)

    p_actions = sub.add_parser("actions", help="list the actions a package exposes")
    p_actions.add_argument("package_id")
    p_actions.set_defaults(func=_cli_actions)

    p_run = sub.add_parser("run", help="run one of a package's actions")
    p_run.add_argument("package_id")
    p_run.add_argument("action_id")
    p_run.add_argument(
        "--set", action="append", metavar="key=value", help="supply a parameter; repeatable"
    )
    p_run.add_argument(
        "--yes", action="store_true", help="never prompt; fail if input is needed"
    )
    p_run.set_defaults(func=_cli_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (EOFError, KeyboardInterrupt):
        # Ctrl-C, or stdin closed on a command that still had something to
        # ask -- a traceback would suggest a bug rather than a cancellation.
        print("\ncancelled", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
