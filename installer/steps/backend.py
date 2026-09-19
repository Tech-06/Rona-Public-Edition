"""Install step: the backend (backend/.venv + requirements + .env skeleton
+ create_db.py). AUTH_TOKEN generation is handled centrally by
installer/main.py, since it must match web-client/.env too.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from installer import detect, envgen, i18n, ui


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

    ui.ok(i18n.t("steps.backend.done"))
    return True
