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
import contextlib
import getpass
import importlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import toolbox
from toolbox import db, envfile, packages, sources, versions
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


class ManagerBusy(ManagerError):
    """Raised when another install/update/uninstall already holds the lock."""


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
class PreviousInstall:
    """What an upgrade is replacing -- kept around so a failure can put it
    back exactly as it was."""

    manifest: PackageManifest | None
    backup_dir: Path
    lock_entry: dict[str, Any] | None


@dataclass
class StagedPackage:
    manifest: PackageManifest
    pkg_dir: Path
    entry: CatalogEntry
    env_snapshot: dict[str, str | None] = dataclass_field(default_factory=dict)
    # File names a previous uninstall parked aside and this install put back.
    restored_user_data: list[str] = dataclass_field(default_factory=list)
    # Set only when this StagedPackage is an *upgrade* of an already
    # -installed package (see stage_upgrade / update()). None means a fresh
    # install -- rollback_staged uses this to tell the two apart.
    previous: "PreviousInstall | None" = None
    # Required config keys still unset because defer_config=True let the
    # install/update proceed anyway.
    config_pending: list[str] = dataclass_field(default_factory=list)
    health: "HealthResult | None" = None
    # Whether `pip install` actually changed anything for this package.
    pip_changed: bool = False


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
    """One package an install/update would touch, worked out from the catalog
    index alone (nothing is downloaded to build this)."""

    id: str
    name: str
    version: str
    kind: str
    reason: Literal["requested", "dependency", "upgrade"]
    already_installed: bool
    installed_version: str | None = None

    @property
    def needs_action(self) -> bool:
        """True when this entry means something will actually happen to it
        (installed fresh, or upgraded) rather than just being reported as
        already satisfied."""
        return self.reason in ("requested", "upgrade") or not self.already_installed


@dataclass
class UninstallResult:
    # Installed packages that declared a dependency on the removed one (only
    # non-empty when force=True was needed to get past them).
    dependents: list[str]
    # File names moved aside instead of deleted, restored on a reinstall.
    preserved: list[str]


@dataclass
class _Run:
    """Everything one install()/update() call threads through the recursive
    resolver, gathered in one place so adding a new piece of state doesn't
    mean widening every function's parameter list again."""

    source_obj: CatalogSource
    # The catalog index, fetched once per run rather than once per package.
    entries: dict[str, CatalogEntry]
    answers: dict[str, dict[str, Any]]
    on_missing_config: OnMissingConfig | None
    on_health_result: OnHealthResult | None
    keep_on_health_failure: bool
    defer_config: bool
    staged: list[StagedPackage] = dataclass_field(default_factory=list)
    in_progress: set[str] = dataclass_field(default_factory=set)

    def entry(self, package_id: str, required_by: str | None = None) -> CatalogEntry:
        found = self.entries.get(package_id)
        if found is None:
            where = f" (required by '{required_by}')" if required_by else ""
            raise SourceError(f"package '{package_id}' not found in catalog{where}")
        return found

    def staged_version(self, package_id: str) -> str | None:
        for sp in self.staged:
            if sp.manifest.id == package_id:
                return sp.manifest.version
        return None


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
# Progress / locking / crash recovery
# ---------------------------------------------------------------------------


def _progress(msg: str) -> None:
    """One line of human-readable progress on stderr.

    Installs and updates can take a while (a git sparse-checkout, a pip
    install...) with nothing else to show for it in the meantime; a caller
    that doesn't care (the test suite, a non-interactive script) just never
    reads stderr.
    """
    print(f"[toolbox] {msg}", file=sys.stderr, flush=True)


def _catalog_entries(source_obj: CatalogSource) -> dict[str, CatalogEntry]:
    _progress("fetching catalog index...")
    return {e.id: e for e in source_obj.fetch_index()}


@contextlib.contextmanager
def _exclusive_lock():
    """Only one install/update/uninstall may run at a time.

    Two concurrent runs racing to swap the same package's files (or even two
    different packages, since both touch the shared lockfile) is how you get
    a half-written installed.json or a package directory with one foot in
    each version. A plain lock file, held for the whole call, rules that out
    -- ``ManagerBusy`` tells a caller to just try again shortly rather than
    hang waiting for it.
    """
    lock_path = packages.CUSTOM_DIR / ".manager.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+b")
    try:
        if sys.platform == "win32":
            import msvcrt

            fh.seek(0)
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ManagerBusy(
                    "another package install/update/uninstall is already running"
                ) from exc
        else:
            import fcntl

            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ManagerBusy(
                    "another package install/update/uninstall is already running"
                ) from exc
        yield
    finally:
        try:
            if sys.platform == "win32":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        fh.close()


def _rename_with_retry(src: Path, dst: Path, attempts: int = 5, delay: float = 0.4) -> None:
    """os.replace with a few retries -- on Windows a file can be briefly held
    open (an antivirus scan, an editor, a lingering handle from a health
    check import) right when an update wants to swap it out from under
    itself."""
    last_exc: Exception | None = None
    for _ in range(attempts):
        try:
            os.replace(src, dst)
            return
        except OSError as exc:
            last_exc = exc
            time.sleep(delay)
    raise ManagerError(f"could not move {src} to {dst}: {last_exc}")


def _recover_interrupted_updates() -> None:
    """Called under the lock at the start of every install/update/uninstall:
    put things back in a consistent state if a *previous* run got killed
    (process crash, BFF/CLI terminated) partway through swapping a package's
    files.

    ``_swap_in`` leaves at most one of these behind if interrupted:
      - ``<id>.old`` with no live ``custom/<id>``: the rename that would have
        put the old version back never ran -- restore it.
      - ``<id>.old`` alongside a live ``custom/<id>``: the swap completed
        (the new version is live), only the old backup's cleanup never ran
        -- just delete it.
      - a stray ``<id>.new`` or ``<id>.trash``: leftovers from a step that
        never finished; neither is ever needed afterwards.
    """
    updating_dir = packages.UPDATING_DIR
    if not updating_dir.is_dir():
        return
    for old_backup in updating_dir.glob("*.old"):
        pkg_id = old_backup.name[: -len(".old")]
        live_dir = packages.package_dir(pkg_id)
        if not live_dir.exists():
            _progress(f"recovering interrupted update of {pkg_id}...")
            _rename_with_retry(old_backup, live_dir)
        else:
            shutil.rmtree(old_backup, ignore_errors=True)
    for leftover in list(updating_dir.glob("*.new")) + list(updating_dir.glob("*.trash")):
        shutil.rmtree(leftover, ignore_errors=True)
    try:
        updating_dir.rmdir()
    except OSError:
        pass  # not empty (something we don't recognize) or doesn't exist -- fine


def _check_constraint(version: str, requirement: "versions.Requirement", required_by: str) -> None:
    if not requirement.is_satisfied_by(version):
        raise ManagerError(
            f"'{required_by}' requires {requirement}, but the catalog offers {version}"
        )


def _check_dependents_allow(package_id: str, new_version: str) -> None:
    """If ``package_id`` were upgraded to ``new_version``, would every other
    *installed* package that depends on it still have its constraint
    satisfied? Raises if not -- an upgrade must never silently break a
    sibling package."""
    for m in packages.load_installed_manifests():
        if m.id == package_id:
            continue
        for req in m.requirements():
            if req.name == package_id and not req.is_satisfied_by(new_version):
                raise ManagerError(
                    f"cannot update '{package_id}' to {new_version}: "
                    f"'{m.id}' requires {req}"
                )


# ---------------------------------------------------------------------------
# Staging: fetch + validate + pip install + place on disk + schema
# ---------------------------------------------------------------------------


def _declared_tool_names(pkg_dir: Path, manifest: PackageManifest) -> set[str]:
    raw = packages.load_tools_raw(pkg_dir, manifest)
    return {item["name"] for item in raw if isinstance(item, dict) and "name" in item}


def _pip_install(requirements: list[str]) -> bool:
    """Returns True iff pip actually installed/changed something (used to
    decide whether a restart is worth recommending afterwards)."""
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                *requirements,
            ],
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
    return "Successfully installed" in result.stdout


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
        _progress(f"fetching {entry.id} {entry.version}...")
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

        pip_changed = False
        if manifest.python_requirements:
            _progress(f"installing python requirements for {entry.id}...")
            pip_changed = _pip_install(manifest.python_requirements)
            _progress(f"installing python requirements for {entry.id}... done")

        _progress(f"placing files for {entry.id}...")
        shutil.copytree(staging_dir, final_dir)

    try:
        if manifest.schema_sql:
            _progress(f"applying schema for {entry.id}...")
            _apply_schema(final_dir / manifest.schema_sql)
    except Exception:
        shutil.rmtree(final_dir, ignore_errors=True)
        raise

    restored = _restore_user_data(manifest.id, final_dir)
    return StagedPackage(
        manifest=manifest,
        pkg_dir=final_dir,
        entry=entry,
        restored_user_data=restored,
        pip_changed=pip_changed,
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
# Upgrade staging: fetch a new version, carry the old install's data over,
# and atomically swap it in for the version currently on disk.
# ---------------------------------------------------------------------------


def _read_lock_entry(package_id: str) -> dict[str, Any] | None:
    return packages.read_lockfile()["packages"].get(package_id)


def _carry_over(
    old_dir: Path,
    old_manifest: PackageManifest | None,
    staging_dir: Path,
    new_manifest: PackageManifest,
) -> list[str]:
    """Copy user data from the currently-installed package into the freshly
    -fetched staging directory, before it becomes the live one.

    The user's existing copy wins over whatever the new version ships (a
    default config.json, say): every file this touches overwrites the
    package's own copy in ``staging_dir`` rather than the other way round.
    Returns the file names copied, the same shape ``restored_user_data``
    already uses for a preserved-on-uninstall reinstall.
    """
    restored: list[str] = []
    old_config = old_dir / "config.json"
    if old_config.is_file():
        shutil.copy2(old_config, staging_dir / "config.json")

    if old_manifest is not None:
        for field_ in old_manifest.config:
            if field_.target != "file":
                continue
            src_name = field_.dest_filename or field_.key
            src = old_dir / src_name
            if not src.is_file():
                continue
            new_field = next(
                (
                    f
                    for f in new_manifest.config
                    if f.key == field_.key and f.target == "file"
                ),
                None,
            )
            dst_name = (new_field.dest_filename or new_field.key) if new_field else src_name
            shutil.copy2(src, staging_dir / dst_name)
            restored.append(dst_name)

    old_globs = set(old_manifest.user_data_globs) if old_manifest else set()
    new_globs = set(new_manifest.user_data_globs)
    for path in packages.match_user_data(old_dir, old_globs | new_globs, new_manifest.id):
        shutil.copy2(path, staging_dir / path.name)
        restored.append(path.name)
    return restored


def _swap_in(staging_dir: Path, package_id: str) -> Path:
    """Turn ``staging_dir`` into the live package, backing up whatever was
    there before.

    Goes through an intermediate copy in ``UPDATING_DIR`` (rather than
    renaming ``staging_dir`` itself into place) because ``staging_dir`` lives
    inside a ``TemporaryDirectory`` that is on the same filesystem only by
    chance -- ``os.replace`` across filesystems fails outright, whereas the
    copy always works. Returns the backup directory the old version was
    moved to (rollback restores from it; a successful finalize deletes it).
    """
    updating_dir = packages.UPDATING_DIR
    updating_dir.mkdir(parents=True, exist_ok=True)
    new_backup = updating_dir / f"{package_id}.new"
    old_backup = updating_dir / f"{package_id}.old"
    if new_backup.exists():
        shutil.rmtree(new_backup, ignore_errors=True)
    if old_backup.exists():
        shutil.rmtree(old_backup, ignore_errors=True)
    shutil.copytree(staging_dir, new_backup)
    live_dir = packages.package_dir(package_id)
    try:
        _rename_with_retry(live_dir, old_backup)
    except ManagerError:
        shutil.rmtree(new_backup, ignore_errors=True)
        raise ManagerError(
            f"could not update '{package_id}': files in use? stop the backend and retry"
        )
    try:
        _rename_with_retry(new_backup, live_dir)
    except ManagerError:
        _rename_with_retry(old_backup, live_dir)
        raise
    return old_backup


def stage_upgrade(entry: CatalogEntry, run: "_Run") -> StagedPackage:
    """Fetch a newer version of an *already-installed* package, carry its
    user data and configuration over, and swap it in for the version on
    disk. Mirrors ``stage()`` (fetch, tool-name-conflict check, pip install,
    schema) but replaces "copy into a brand-new directory" with "swap the
    live directory for a new one while keeping a restorable backup"."""
    package_id = entry.id
    old_dir = packages.package_dir(package_id)
    try:
        old_manifest = packages.load_manifest(old_dir)
    except packages.PackageLoadError:
        old_manifest = None
    lock_entry = _read_lock_entry(package_id)

    _check_dependents_allow(package_id, entry.version)
    _progress(
        f"upgrading {package_id} {old_manifest.version if old_manifest else '?'} "
        f"-> {entry.version}"
    )

    with tempfile.TemporaryDirectory(prefix=f"rona-stage-{package_id}-") as tmp_name:
        staging_dir = Path(tmp_name) / package_id
        _progress(f"fetching {package_id} {entry.version}...")
        run.source_obj.fetch_package(entry, staging_dir)
        new_manifest = packages.load_manifest(staging_dir)
        if new_manifest.id != package_id:
            raise ManagerError(
                f"catalog entry '{package_id}' fetched a manifest for '{new_manifest.id}'"
            )

        declared = _declared_tool_names(staging_dir, new_manifest)
        # A package's own previous version is still loaded right now -- its
        # tool names must not count as a conflict against its own new ones.
        existing = {
            spec.name
            for spec in toolbox.iter_specs()
            if not spec.module.startswith(f"toolbox.custom.{package_id}.")
        }
        conflicts = declared & existing
        if conflicts:
            raise ToolNameConflict(
                f"package '{new_manifest.id}' provides tool(s) that already exist: "
                f"{', '.join(sorted(conflicts))}"
            )

        pip_changed = False
        if new_manifest.python_requirements:
            _progress(f"installing python requirements for {package_id}...")
            pip_changed = _pip_install(new_manifest.python_requirements)
            _progress(f"installing python requirements for {package_id}... done")

        _progress(f"placing files for {package_id}...")
        restored = _carry_over(old_dir, old_manifest, staging_dir, new_manifest)
        backup_dir = _swap_in(staging_dir, package_id)

    staged = StagedPackage(
        manifest=new_manifest,
        pkg_dir=packages.package_dir(package_id),
        entry=entry,
        restored_user_data=restored,
        previous=PreviousInstall(
            manifest=old_manifest, backup_dir=backup_dir, lock_entry=lock_entry
        ),
        pip_changed=pip_changed,
    )
    # Appended before the schema step (which can still fail) runs, so the
    # caller's rollback loop knows to put the old version back rather than
    # leaving the live directory holding a half-configured new one.
    run.staged.append(staged)

    if new_manifest.schema_sql:
        _progress(f"applying schema for {package_id}...")
        _apply_schema(staged.pkg_dir / new_manifest.schema_sql)

    toolbox.purge_package_modules([package_id])
    toolbox.reload_registry()
    return staged


def _restore_previous(staged: StagedPackage) -> None:
    """Undo one upgrade: move the (broken, cancelled, or otherwise unwanted)
    new version out of the way and put the backed-up old one back, including
    its lockfile entry."""
    assert staged.previous is not None
    package_id = staged.manifest.id
    live_dir = packages.package_dir(package_id)
    updating_dir = packages.UPDATING_DIR
    trash = updating_dir / f"{package_id}.trash"
    if trash.exists():
        shutil.rmtree(trash, ignore_errors=True)
    if live_dir.exists():
        try:
            _rename_with_retry(live_dir, trash)
            shutil.rmtree(trash, ignore_errors=True)
        except ManagerError:
            pass  # worst case the live dir is left as-is, overwritten below
    backup_dir = staged.previous.backup_dir
    if backup_dir.exists():
        _rename_with_retry(backup_dir, live_dir)
    if staged.previous.lock_entry is not None:
        packages.record_install(
            package_id,
            staged.previous.lock_entry["version"],
            staged.previous.lock_entry.get("source", ""),
            staged.previous.lock_entry.get("installed_at", ""),
        )
    else:
        packages.record_uninstall(package_id)


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


def apply_config(
    staged: StagedPackage, answers: dict[str, Any], *, allow_missing: bool = False
) -> None:
    """Validate and persist every declared config field for a staged package.

    All-or-nothing: if a required field is missing, nothing is written --
    unless ``allow_missing=True`` (install/update's ``--defer-config``),
    which writes whatever *was* given and leaves the rest for later.
    """
    manifest = staged.manifest
    missing = [f.key for f in manifest.config if f.required and answers.get(f.key) in (None, "")]
    if missing and not allow_missing:
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


def _stored_answers(manifest: PackageManifest) -> dict[str, Any]:
    """What's already on disk for every one of ``manifest``'s config fields,
    read straight from where each target actually lives (.env, config.json,
    the package directory for a file field).

    ``update()`` passes this to ``_configure_and_verify_one`` as ``existing``
    so an upgrade that carried its config over cleanly doesn't ask again --
    and, just as importantly, doesn't rewrite anything when nothing actually
    changed.
    """
    packages.load_dotenv(packages.ENV_PATH)
    values: dict[str, Any] = {}
    for field_ in manifest.config:
        if field_.target == "env":
            env_var = field_.env_var or f"{manifest.id.upper()}_{field_.key.upper()}"
            value = os.getenv(env_var)
            if value not in (None, ""):
                values[field_.key] = value
        elif field_.target == "file":
            dest = packages.package_dir(manifest.id) / (field_.dest_filename or field_.key)
            if dest.is_file():
                values[field_.key] = str(dest)
        else:
            stored = packages.read_config_file(manifest.id)
            if field_.key in stored:
                values[field_.key] = stored[field_.key]
    return values


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
    return run_health_check(installed_manifest(package_id))


def installed_manifest(package_id: str) -> PackageManifest:
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
    manifest = installed_manifest(package_id)
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
    manifest = installed_manifest(package_id)
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
    _progress(f"rolling back {staged.manifest.id}...")
    if staged.previous is not None:
        _restore_previous(staged)
    else:
        shutil.rmtree(staged.pkg_dir, ignore_errors=True)
        packages.record_uninstall(staged.manifest.id)
    if staged.env_snapshot:
        _restore_env(staged.env_snapshot)
    toolbox.purge_package_modules([staged.manifest.id])
    toolbox.reload_registry()


def finalize(staged: StagedPackage, source_spec: str) -> None:
    packages.record_install(
        staged.manifest.id,
        staged.manifest.version,
        source_spec,
        datetime.now(timezone.utc).isoformat(),
    )
    if staged.previous is not None:
        backup_dir = staged.previous.backup_dir
        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)
        try:
            packages.UPDATING_DIR.rmdir()
        except OSError:
            pass  # other packages' backups (or something else) still in there


# ---------------------------------------------------------------------------
# Install orchestration
# ---------------------------------------------------------------------------


def _configure_and_verify_one(
    staged: StagedPackage,
    run: "_Run",
    *,
    existing: dict[str, Any] | None = None,
) -> HealthResult:
    """Collect config, apply it, reload the registry and run the health
    check for one staged package -- shared by a fresh install
    (``existing=None``) and an upgrade (``existing=_stored_answers(...)``).

    For an upgrade, ``existing`` is what's already on disk (carried over from
    the previous version); only fields still missing after overlaying the
    run's ``answers`` on top of that are actually "missing". And since an
    upgrade's config is usually already satisfied, ``apply_config`` is only
    called when there is something new to write -- a no-op update must not
    touch config.json/.env/a copied file just because it re-ran the same
    values through it.
    """
    manifest = staged.manifest
    pkg_answers = dict(run.answers.get(manifest.id, {}))
    baseline = dict(existing or {})

    def missing_fields() -> list[ConfigField]:
        merged = {**baseline, **pkg_answers}
        return [f for f in manifest.config if f.required and merged.get(f.key) in (None, "")]

    missing = missing_fields()

    if missing and run.defer_config:
        if pkg_answers:
            _progress(f"applying configuration for {manifest.id}...")
            apply_config(staged, pkg_answers, allow_missing=True)
        staged.config_pending = [f.key for f in missing]
        toolbox.purge_package_modules([manifest.id])
        toolbox.reload_registry()
        if manifest.id in toolbox.failed_packages():
            raise ManagerError(f"'{manifest.id}' failed to load: see server log")
        result = HealthResult(
            ok=False,
            detail=f"configuration pending: {', '.join(f.key for f in missing)}",
        )
        staged.health = result
        return result

    while True:
        missing = missing_fields()
        if missing:
            if run.on_missing_config is None:
                raise ManagerError(
                    f"package '{manifest.id}' needs config: "
                    + ", ".join(f.key for f in missing)
                )
            pkg_answers.update(run.on_missing_config(staged, missing))
            continue

        # A plain "nothing changed" update writes nothing: apply_config only
        # runs for a fresh install (existing is None) or when this run
        # actually collected/was given new values for this package.
        if existing is None or pkg_answers:
            _progress(f"applying configuration for {manifest.id}...")
            apply_config(staged, pkg_answers)
        toolbox.purge_package_modules([manifest.id])
        toolbox.reload_registry()
        if manifest.id in toolbox.failed_packages():
            raise ManagerError(f"'{manifest.id}' failed to load: see server log")

        _progress(f"running health check for {manifest.id}...")
        result = run_health_check(manifest)
        staged.health = result
        if result.ok or run.keep_on_health_failure:
            return result
        if run.on_health_result is None:
            raise HealthCheckFailed(result.detail, staged)
        decision = run.on_health_result(staged, result)
        if decision == "keep":
            return result
        if decision == "cancel":
            raise InstallCancelled(
                f"installation of '{manifest.id}' cancelled after failed health check"
            )
        if decision == "retry":
            if run.on_missing_config is None:
                # A caller that supplied on_health_result but not
                # on_missing_config has no way to collect corrected values;
                # treat the retry as unsatisfiable rather than crashing.
                raise HealthCheckFailed(result.detail, staged)
            pkg_answers.update(run.on_missing_config(staged, list(manifest.config)))
            continue
        raise ManagerError(f"unknown health-check decision: {decision!r}")


def _install_recursive(
    package_id: str,
    run: "_Run",
    *,
    requirement: "versions.Requirement | None" = None,
    required_by: str | None = None,
) -> None:
    """Make sure ``package_id`` ends up installed and satisfying
    ``requirement`` (fresh, or upgraded in place if it's installed but too
    old), then do the same for everything it in turn requires."""
    if package_id in run.in_progress:
        # Must be checked before the "already done" shortcuts below: a
        # package that is still being staged (its own `requires` are being
        # walked right now) is by definition not finished yet, even though
        # it may already be sitting in run.staged.
        raise DependencyCycle(f"circular 'requires' dependency involving '{package_id}'")

    staged_version = run.staged_version(package_id)
    if staged_version is not None:
        if requirement is not None and not requirement.is_satisfied_by(staged_version):
            raise ManagerError(
                f"'{required_by}' requires {requirement}, but this install resolved "
                f"'{package_id}' to {staged_version}"
            )
        return

    if is_installed(package_id):
        manifest = packages.load_manifest(packages.package_dir(package_id))
        if requirement is None or requirement.is_satisfied_by(manifest.version):
            return
        _upgrade_one(package_id, run, requirement=requirement, required_by=required_by)
        return

    run.in_progress.add(package_id)
    entry = run.entry(package_id, required_by)
    if requirement is not None:
        _check_constraint(entry.version, requirement, required_by or package_id)

    staged = stage(entry, run.source_obj)
    run.staged.append(staged)

    for req in staged.manifest.requirements():
        _install_recursive(
            req.name, run, requirement=req if req.specifiers else None, required_by=package_id
        )

    _configure_and_verify_one(staged, run)
    run.in_progress.discard(package_id)


def _upgrade_one(
    package_id: str,
    run: "_Run",
    *,
    requirement: "versions.Requirement | None" = None,
    required_by: str | None = None,
) -> None:
    """Upgrade an already-installed package to what the catalog offers (and
    make sure whatever it now requires is installed/upgraded too)."""
    if package_id in run.in_progress:
        raise DependencyCycle(f"circular 'requires' dependency involving '{package_id}'")
    if run.staged_version(package_id) is not None:
        return

    run.in_progress.add(package_id)
    entry = run.entry(package_id, required_by)
    if requirement is not None:
        _check_constraint(entry.version, requirement, required_by or package_id)

    staged = stage_upgrade(entry, run)

    for req in staged.manifest.requirements():
        _install_recursive(
            req.name, run, requirement=req if req.specifiers else None, required_by=package_id
        )

    _configure_and_verify_one(staged, run, existing=_stored_answers(staged.manifest))
    run.in_progress.discard(package_id)


def resolve_plan(
    package_id: str,
    source_obj: CatalogSource,
    *,
    mode: str = "install",
    entries: dict[str, CatalogEntry] | None = None,
) -> tuple[list[PlanEntry], bool]:
    """What installing/updating ``package_id`` would touch, from the index
    alone -- nothing is downloaded, which is the only way to tell a user what
    is about to happen *before* it happens.

    ``mode="install"`` is the original behaviour: walk ``package_id`` (which
    isn't installed yet) and everything it requires, in dependency-first
    order. ``mode="update"`` additionally lets the *root* package itself
    count as something to act on when the catalog offers a newer version
    than what's installed.

    A node already installed and satisfying whatever pulled it in is
    reported (``already_installed=True``) but its own ``requires`` are not
    walked -- it isn't being touched, so there is nothing new to resolve
    underneath it. A node that *is* being installed or upgraded gets
    ``reason="dependency"``/``"upgrade"`` and its requirements are walked,
    same as the root.

    Returns the entries in install order (dependencies first) plus a
    ``complete`` flag. ``complete`` is False when something this plan
    actually needs to act on did not declare ``requires`` in the index at
    all -- an older catalog. The plan is then a lower bound, and callers must
    say so rather than present it as the whole story.
    """
    if entries is None:
        entries = {entry.id: entry for entry in source_obj.fetch_index()}
    plan: list[PlanEntry] = []
    seen: set[str] = set()
    complete = True

    def installed_version_of(pkg_id: str) -> str | None:
        if not is_installed(pkg_id):
            return None
        try:
            return packages.load_manifest(packages.package_dir(pkg_id)).version
        except packages.PackageLoadError:
            return None

    def walk(
        pkg_id: str,
        chain: tuple[str, ...],
        requirement: "versions.Requirement | None",
        is_root: bool,
    ) -> None:
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

        installed_version = installed_version_of(pkg_id)
        touches: bool
        if installed_version is None:
            reason = "requested" if is_root else "dependency"
            touches = True
        elif requirement is not None and not requirement.is_satisfied_by(installed_version):
            reason = "requested" if is_root else "upgrade"
            touches = True
        elif is_root and mode == "update" and versions.is_newer(entry.version, installed_version):
            reason = "requested"
            touches = True
        else:
            reason = "requested" if is_root else "dependency"
            touches = False

        if touches and requirement is not None:
            _check_constraint(entry.version, requirement, chain[-1] if chain else pkg_id)

        if touches:
            if entry.requires is None:
                complete = False
            for req in entry.requirements() or ():
                walk(req.name, chain + (pkg_id,), req if req.specifiers else None, False)

        plan.append(
            PlanEntry(
                id=entry.id,
                name=entry.name,
                version=entry.version,
                kind=entry.kind,
                reason=reason,
                already_installed=installed_version is not None,
                installed_version=installed_version,
            )
        )

    walk(package_id, (), None, True)
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
    defer_config: bool = False,
) -> list[StagedPackage]:
    """Install ``package_id`` and any not-yet-installed (or too-old)
    dependencies.

    Returns the list of packages staged during this call (in install
    order). On any failure or cancellation, every one of them is rolled
    back before the exception propagates -- the repository ends up exactly
    as it was before the call.

    ``on_plan``, when given, is consulted *before anything is downloaded* and
    only when the install would actually bring in or upgrade a dependency;
    returning False cancels. A catalog that doesn't publish dependency
    metadata therefore never prompts -- the install simply behaves as it
    always did and resolves requires from each manifest as it goes.

    Only one install/update/uninstall may run at a time (see
    ``_exclusive_lock``); a previous run left half-finished by a crash is
    cleaned up before this one starts.
    """
    with _exclusive_lock():
        _recover_interrupted_updates()
        if is_installed(package_id):
            raise PackageAlreadyInstalled(f"'{package_id}' is already installed; use update")

        source_obj = sources.parse_source(source)
        entries = _catalog_entries(source_obj)

        if on_plan is not None:
            plan, complete = resolve_plan(package_id, source_obj, entries=entries)
            extra = [e for e in plan if e.reason != "requested" and e.needs_action]
            if extra and not on_plan(plan, complete):
                raise InstallCancelled(f"installation of '{package_id}' cancelled")

        run = _Run(
            source_obj=source_obj,
            entries=entries,
            answers=answers or {},
            on_missing_config=on_missing_config,
            on_health_result=on_health_result,
            keep_on_health_failure=keep_on_health_failure,
            defer_config=defer_config,
        )
        try:
            _install_recursive(package_id, run)
        except Exception:
            for staged in reversed(run.staged):
                rollback_staged(staged)
            raise

        for staged in run.staged:
            finalize(staged, source)
        return run.staged


def update(
    package_id: str,
    *,
    source: str = sources.DEFAULT_CATALOG_SOURCE,
    answers: dict[str, dict[str, Any]] | None = None,
    on_missing_config: OnMissingConfig | None = None,
    on_health_result: OnHealthResult | None = None,
    on_plan: OnPlan | None = None,
    keep_on_health_failure: bool = False,
    defer_config: bool = False,
) -> list[StagedPackage]:
    """Upgrade an already-installed ``package_id`` to what the catalog
    offers, and any dependency that needs upgrading (or installing) to keep
    up with it.

    Returns ``[]`` -- without downloading, locking anything longer than the
    check takes, or calling any callback -- when the catalog's version is not
    newer than what's installed. Otherwise behaves like ``install``: rolled
    back completely on failure/cancellation, finalized (lockfile updated)
    package by package on success.
    """
    with _exclusive_lock():
        _recover_interrupted_updates()
        if not is_installed(package_id):
            raise ManagerError(f"'{package_id}' is not installed")

        source_obj = sources.parse_source(source)
        entries = _catalog_entries(source_obj)

        plan, complete = resolve_plan(package_id, source_obj, mode="update", entries=entries)
        if len(plan) == 1 and plan[0].reason == "requested" and plan[0].already_installed:
            catalog_version = entries[package_id].version
            installed = packages.load_manifest(packages.package_dir(package_id))
            if not versions.is_newer(catalog_version, installed.version):
                return []

        if on_plan is not None:
            extra = [e for e in plan if e.reason != "requested" and e.needs_action]
            if extra and not on_plan(plan, complete):
                raise InstallCancelled(f"update of '{package_id}' cancelled")

        run = _Run(
            source_obj=source_obj,
            entries=entries,
            answers=answers or {},
            on_missing_config=on_missing_config,
            on_health_result=on_health_result,
            keep_on_health_failure=keep_on_health_failure,
            defer_config=defer_config,
        )
        try:
            _upgrade_one(package_id, run)
        except Exception:
            for staged in reversed(run.staged):
                rollback_staged(staged)
            raise

        for staged in run.staged:
            finalize(staged, source)
        return run.staged


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
    with _exclusive_lock():
        _recover_interrupted_updates()
        pkg_dir = packages.package_dir(package_id)
        if not pkg_dir.is_dir():
            raise ManagerError(f"'{package_id}' is not installed")

        dependents = [
            m.id
            for m in packages.load_installed_manifests()
            if m.id != package_id and package_id in m.required_ids()
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
                # A corrupt package still has to be removable; it just can't
                # tell us which of its files are user data.
                manifest = None
            user_data = packages.user_data_paths(manifest) if manifest else []
            if user_data and (
                on_user_data is None or on_user_data(package_id, list(user_data))
            ):
                parked = packages.preserved_dir(package_id)
                parked.mkdir(parents=True, exist_ok=True)
                for path in user_data:
                    dest = parked / path.name
                    if dest.exists():
                        dest.unlink()
                    shutil.move(str(path), str(dest))
                    preserved.append(path.name)

        _progress(f"removing {package_id}...")
        updating_dir = packages.UPDATING_DIR
        updating_dir.mkdir(parents=True, exist_ok=True)
        trash = updating_dir / f"{package_id}.trash"
        if trash.exists():
            shutil.rmtree(trash, ignore_errors=True)
        _rename_with_retry(pkg_dir, trash)
        shutil.rmtree(trash, ignore_errors=True)
        packages.record_uninstall(package_id)
        toolbox.purge_package_modules([package_id])
        toolbox.reload_registry()
        try:
            updating_dir.rmdir()
        except OSError:
            pass  # other packages' backups (or something else) still in there

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
    extra = [e for e in plan if e.reason != "requested" and e.needs_action]
    print(f"\n'{requested.id}' also needs:")
    for entry in extra:
        if entry.reason == "upgrade":
            print(f"  {entry.id}  {entry.installed_version} -> {entry.version}  (upgrade)")
        else:
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


def _make_on_missing_config(
    args: argparse.Namespace, raw_answers: dict[str, dict[str, Any]]
) -> OnMissingConfig:
    """Shared by ``install`` and ``update``: prefer a pre-supplied ``--set``
    value, coerced to the field's declared type; prompt for the rest unless
    ``--yes`` was given, in which case missing config is a hard error."""

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

    return on_missing_config


def _result_payload(staged: list[StagedPackage]) -> dict[str, Any]:
    """JSON payload shared by ``install`` and ``update``'s CLI: which
    packages were freshly installed vs. upgraded, what config is still
    pending (``--defer-config``), each one's health, and whether a pip
    install means the backend should be restarted to pick it up."""
    installed = [sp.manifest.id for sp in staged if sp.previous is None]
    upgraded = [
        {
            "id": sp.manifest.id,
            "from": (sp.previous.manifest.version if sp.previous.manifest else "?"),
            "to": sp.manifest.version,
        }
        for sp in staged
        if sp.previous is not None
    ]
    config_pending = {sp.manifest.id: sp.config_pending for sp in staged if sp.config_pending}
    health = {
        sp.manifest.id: {"ok": sp.health.ok, "detail": sp.health.detail}
        for sp in staged
        if sp.health is not None
    }
    restart_recommended = any(sp.pip_changed for sp in staged)
    restored = sorted({name for sp in staged for name in sp.restored_user_data})
    payload: dict[str, Any] = {
        "ok": True,
        "installed": installed,
        "upgraded": upgraded,
        "config_pending": config_pending,
        "health": health,
        "restart_recommended": restart_recommended,
        "note": "restart the backend for it to pick up the new tool(s)",
    }
    if restored:
        payload["restored"] = restored
    return payload


def _cli_install(args: argparse.Namespace) -> int:
    raw_answers = _parse_set_args(args.set or [], args.package_id)
    # CLI values arrive as strings; coerce them once we know each field's
    # declared type (done lazily inside the missing-config callback so we
    # only need the manifest, not a second pass over raw_answers here).
    on_missing_config = _make_on_missing_config(args, raw_answers)
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
            defer_config=args.defer_config,
        )
    # SourceError and PackageLoadError are not ManagerError subclasses: an
    # unreachable catalog or a malformed manifest used to escape as a raw
    # traceback here, which the CLI then reported as "no output from the
    # manager" rather than the real reason. ManagerBusy is a ManagerError
    # subclass and so is already covered.
    except (ManagerError, SourceError, packages.PackageLoadError) as exc:
        _emit(args, {"ok": False, "error": str(exc)})
        return 1

    _emit(args, _result_payload(staged))
    return 0


def _cli_update(args: argparse.Namespace) -> int:
    raw_answers = _parse_set_args(args.set or [], args.package_id)
    on_missing_config = _make_on_missing_config(args, raw_answers)
    on_health_result = None if args.yes else _prompt_health_decision
    # --yes means "don't block on anything" -- a failed health check on an
    # otherwise-successful update is reported, not treated as a reason to
    # roll a perfectly good upgrade back.
    keep_on_health_failure = args.keep_on_health_failure or args.yes

    try:
        staged = update(
            args.package_id,
            source=args.source,
            answers={pkg_id: dict(vals) for pkg_id, vals in raw_answers.items()},
            on_missing_config=on_missing_config,
            on_health_result=on_health_result,
            on_plan=None if args.yes else _prompt_plan,
            keep_on_health_failure=keep_on_health_failure,
            defer_config=args.defer_config,
        )
    except (ManagerError, SourceError, packages.PackageLoadError) as exc:
        _emit(args, {"ok": False, "error": str(exc)})
        return 1

    if not staged:
        installed = packages.load_manifest(packages.package_dir(args.package_id))
        _emit(
            args,
            {
                "ok": True,
                "up_to_date": True,
                "package": args.package_id,
                "version": installed.version,
                "installed": [],
                "upgraded": [],
                "config_pending": {},
                "health": {},
                "restart_recommended": False,
            },
        )
        return 0

    _emit(args, _result_payload(staged))
    return 0


def _cli_plan(args: argparse.Namespace) -> int:
    try:
        source_obj = sources.parse_source(args.source)
        mode = "update" if is_installed(args.package_id) else "install"
        entries = _catalog_entries(source_obj)
        plan, complete = resolve_plan(args.package_id, source_obj, mode=mode, entries=entries)
        up_to_date = False
        if mode == "update" and len(plan) == 1 and plan[0].already_installed:
            catalog_version = entries[args.package_id].version
            up_to_date = not versions.is_newer(catalog_version, plan[0].installed_version or "0")
    except (ManagerError, SourceError, packages.PackageLoadError) as exc:
        _emit(args, {"ok": False, "error": str(exc)})
        return 1
    _emit(
        args,
        {
            "ok": True,
            "package": args.package_id,
            "action": mode,
            "up_to_date": up_to_date,
            "complete": complete,
            "entries": [
                {
                    "id": e.id,
                    "name": e.name,
                    "version": e.version,
                    "kind": e.kind,
                    "reason": e.reason,
                    "already_installed": e.already_installed,
                    "installed_version": e.installed_version,
                    "needs_action": e.needs_action,
                }
                for e in plan
            ],
        },
    )
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
    installed_manifests = {m.id: m for m in list_installed()}
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
                    "installed_version": (
                        installed_manifests[e.id].version if e.id in installed_manifests else None
                    ),
                    "update_available": (
                        e.id in installed_manifests
                        and versions.is_newer(e.version, installed_manifests[e.id].version)
                    ),
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
        manifest = installed_manifest(args.package_id)
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
        manifest = installed_manifest(args.package_id)
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
        manifest = installed_manifest(args.package_id)
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
    p_install.add_argument(
        "--defer-config",
        action="store_true",
        help="install even if required config is missing, instead of asking/failing; "
        "skips the health check until it's configured",
    )
    p_install.set_defaults(func=_cli_install)

    p_update = sub.add_parser(
        "update", help="upgrade an installed package to what the catalog offers"
    )
    p_update.add_argument("package_id")
    p_update.add_argument("--source", default=sources.DEFAULT_CATALOG_SOURCE)
    p_update.add_argument(
        "--set",
        action="append",
        metavar="[pkg.]key=value",
        help="pre-supply a config value; repeatable",
    )
    p_update.add_argument(
        "--yes", action="store_true", help="never prompt; report (don't fail on) a bad health check"
    )
    p_update.add_argument(
        "--defer-config",
        action="store_true",
        help="update even if required config is missing, instead of asking/failing; "
        "skips the health check until it's configured",
    )
    p_update.add_argument(
        "--keep-on-health-failure",
        action="store_true",
        help="update even if the health check fails, instead of asking/rolling back",
    )
    p_update.set_defaults(func=_cli_update)

    p_plan = sub.add_parser(
        "plan", help="show what installing/updating a package would do, without doing it"
    )
    p_plan.add_argument("package_id")
    p_plan.add_argument("--source", default=sources.DEFAULT_CATALOG_SOURCE)
    p_plan.set_defaults(func=_cli_plan)

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
