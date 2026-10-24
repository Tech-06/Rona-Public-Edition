"""Install step: the backend (backend/.venv + requirements + .env skeleton
+ create_db.py). AUTH_TOKEN generation is handled centrally by
installer/main.py, since it must match web-client/.env too.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from installer import detect, envgen, i18n, ui


def _has_installed_packages(backend_dir: Path) -> bool:
    custom_dir = backend_dir / "toolbox" / "custom"
    if not custom_dir.is_dir():
        return False
    return any(
        p.is_dir() and not p.name.startswith((".", "__")) for p in custom_dir.iterdir()
    )


def _restore_package_deps(python: Path, backend_dir: Path) -> None:
    """Re-pip-install what installed catalog packages declared. Those
    requirements are only installed at package install/update time, so a
    recreated venv (--repair) would otherwise leave google_*, web_search...
    unimportable. Never fatal: the core works without them, so problems are
    warnings the user can act on."""
    ui.info(i18n.t("steps.backend.restoring_package_deps"))
    manager = [str(python), "-m", "toolbox.manager", "--json"]
    try:
        result = subprocess.run(
            [*manager, "reinstall-deps"],
            cwd=backend_dir,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        ui.warn(i18n.t("steps.backend.package_deps_failed", detail=str(exc)))
        return
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip()
        ui.warn(i18n.t("steps.backend.package_deps_failed", detail=detail))
        return

    try:
        package_ids = list(json.loads(result.stdout.strip().splitlines()[-1]).get("packages", []))
    except (ValueError, IndexError, AttributeError):
        package_ids = []

    # verify takes one package id at a time.
    unhealthy: list[str] = []
    for package_id in package_ids:
        check = subprocess.run(
            [*manager, "verify", package_id],
            cwd=backend_dir,
            check=False,
            capture_output=True,
            text=True,
        )
        if check.returncode != 0:
            unhealthy.append(package_id)
    if unhealthy:
        ui.warn(i18n.t("steps.backend.packages_unhealthy", names=", ".join(unhealthy)))
    else:
        ui.ok(i18n.t("steps.backend.package_deps_restored", count=len(package_ids)))


def install(root: Path, *, reinstall: bool) -> bool:
    ui.step(i18n.t("steps.backend.title"))
    backend_dir = root / "backend"
    venv_dir = backend_dir / ".venv"

    if reinstall and venv_dir.exists():
        ui.info(i18n.t("steps.common.removing_venv"))
        shutil.rmtree(venv_dir)

    if not venv_dir.exists():
        ui.info(i18n.t("steps.common.creating_venv"))
        if subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=False).returncode != 0:
            ui.error(i18n.t("steps.common.venv_create_failed"))
            return False

    python = detect.venv_python_path(venv_dir)
    ui.info(i18n.t("steps.backend.installing_deps"))
    subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=False
    )
    result = subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", "-r", "requirements.txt"],
        cwd=backend_dir,
        check=False,
    )
    if result.returncode != 0:
        ui.error(i18n.t("steps.common.deps_failed"))
        return False

    envgen.materialize_env(backend_dir / ".env.example", backend_dir / ".env")

    ui.info(i18n.t("steps.backend.preparing_db"))
    result = subprocess.run([str(python), "create_db.py"], cwd=backend_dir, check=False)
    if result.returncode != 0:
        ui.error(i18n.t("steps.backend.db_failed"))
        return False

    if _has_installed_packages(backend_dir):
        _restore_package_deps(python, backend_dir)

    ui.ok(i18n.t("steps.backend.done"))
    return True
