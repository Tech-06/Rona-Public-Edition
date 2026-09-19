"""Install step: the web dashboard (web-client/.venv + requirements +
.env skeleton + npm ci/install + npm run build).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from installer import detect, envgen, i18n, ui


def install(root: Path, *, reinstall: bool) -> bool:
    ui.step(i18n.t("steps.web.title"))
    web_dir = root / "web-client"
    frontend_dir = web_dir / "frontend"
    venv_dir = web_dir / ".venv"

    if reinstall and venv_dir.exists():
        ui.info(i18n.t("steps.common.removing_venv"))
        shutil.rmtree(venv_dir)

    if not venv_dir.exists():
        ui.info(i18n.t("steps.common.creating_venv"))
        if subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=False).returncode != 0:
            ui.error(i18n.t("steps.common.venv_create_failed"))
            return False

    python = detect.venv_python_path(venv_dir)
    ui.info(i18n.t("steps.web.installing_deps"))
    subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=False
    )
    result = subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", "-r", "requirements.txt"],
        cwd=web_dir,
        check=False,
    )
    if result.returncode != 0:
        ui.error(i18n.t("steps.common.deps_failed"))
        return False

    envgen.materialize_env(web_dir / ".env.example", web_dir / ".env")

    npm = shutil.which("npm")
    if npm is None:
        ui.error(i18n.t("steps.web.npm_not_found"))
        return False

    on_windows = sys.platform == "win32"
    lockfile = frontend_dir / "package-lock.json"
    npm_install_cmd = [npm, "ci"] if lockfile.exists() else [npm, "install"]
    ui.info(i18n.t("steps.web.installing_frontend_deps", cmd=" ".join(npm_install_cmd)))
    result = subprocess.run(npm_install_cmd, cwd=frontend_dir, check=False, shell=on_windows)
    if result.returncode != 0:
        ui.error(i18n.t("steps.web.npm_install_failed"))
        return False

    ui.info(i18n.t("steps.web.building_frontend"))
    result = subprocess.run([npm, "run", "build"], cwd=frontend_dir, check=False, shell=on_windows)
    if result.returncode != 0:
        ui.error(i18n.t("steps.web.npm_build_failed"))
        return False

    ui.ok(i18n.t("steps.web.done"))
    return True
