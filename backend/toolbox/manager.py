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

A non-interactive caller (``--yes`` on the CLI, or the future wizard once it
has collected every answer up front) can simply omit these and pre-fill
``answers``; a missing required value or a failing health check then raises
instead of blocking on input.
"""

from __future__ import annotations

import argparse
import getpass
import importlib
import json
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
from toolbox.packages import ConfigField, PackageManifest
from toolbox.sources import CatalogEntry, CatalogSource, SourceError

_PIP_TIMEOUT_SECONDS = 600

HealthDecision = Literal["retry", "keep", "cancel"]
OnMissingConfig = Callable[["StagedPackage", list[ConfigField]], dict[str, Any]]
OnHealthResult = Callable[["StagedPackage", "HealthResult"], HealthDecision]


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


@dataclass
class HealthResult:
    ok: bool
    detail: str


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

    return StagedPackage(manifest=manifest, pkg_dir=final_dir, entry=entry)


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
    pkg_dir = packages.package_dir(package_id)
    if not pkg_dir.is_dir():
        raise ManagerError(f"'{package_id}' is not installed")
    manifest = packages.load_manifest(pkg_dir)
    return run_health_check(manifest)


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


def install(
    package_id: str,
    *,
    source: str = sources.DEFAULT_CATALOG_SOURCE,
    answers: dict[str, dict[str, Any]] | None = None,
    on_missing_config: OnMissingConfig | None = None,
    on_health_result: OnHealthResult | None = None,
    keep_on_health_failure: bool = False,
) -> list[StagedPackage]:
    """Install ``package_id`` and any not-yet-installed dependencies.

    Returns the list of packages staged during this call (in install
    order). On any failure or cancellation, every one of them is rolled
    back before the exception propagates -- the repository ends up exactly
    as it was before the call.
    """
    source_obj = sources.parse_source(source)
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


def uninstall(package_id: str, *, force: bool = False) -> list[str]:
    """Remove an installed package. Returns the ids of any other installed
    packages that depended on it (only non-empty when ``force=True`` was
    needed to proceed)."""
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
    shutil.rmtree(pkg_dir)
    packages.record_uninstall(package_id)
    toolbox.reload_registry()
    return dependents


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
    print(f"\nConfiguration for '{staged.manifest.id}':")
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
            keep_on_health_failure=args.keep_on_health_failure,
        )
    except ManagerError as exc:
        _emit(args, {"ok": False, "error": str(exc)})
        return 1

    installed_ids = [sp.manifest.id for sp in staged]
    _emit(
        args,
        {
            "ok": True,
            "installed": installed_ids,
            "note": "restart the backend for it to pick up the new tool(s)",
        },
    )
    return 0


def _cli_uninstall(args: argparse.Namespace) -> int:
    try:
        dependents = uninstall(args.package_id, force=args.force)
    except ManagerError as exc:
        _emit(args, {"ok": False, "error": str(exc)})
        return 1
    _emit(args, {"ok": True, "removed": args.package_id, "broken_dependents": dependents})
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
                {"id": e.id, "version": e.version, "name": e.name, "description": e.description}
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
    _emit(args, {"ok": result.ok, "detail": result.detail})
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
    p_uninstall.set_defaults(func=_cli_uninstall)

    p_available = sub.add_parser("available", help="list packages in the catalog")
    p_available.add_argument("--source", default=sources.DEFAULT_CATALOG_SOURCE)
    p_available.set_defaults(func=_cli_available)

    p_installed = sub.add_parser("installed", help="list installed custom packages")
    p_installed.set_defaults(func=_cli_installed)

    p_verify = sub.add_parser("verify", help="re-run an installed package's health check")
    p_verify.add_argument("package_id")
    p_verify.set_defaults(func=_cli_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
