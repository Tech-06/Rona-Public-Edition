"""Install step: the `rona` CLI itself (cli/.venv + pip install -e .).

There's no per-step config to ask -- no CLI-level .env exists (see
cli/README.md) -- so this step is just "make a venv, install the
package." A future config prompt (if one's ever added) would run before
the backend's own questions, per the plan.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from installer import detect, i18n, ui


def install(root: Path, *, reinstall: bool) -> bool:
    ui.step(i18n.t("steps.cli.title"))
    cli_dir = root / "cli"
    venv_dir = cli_dir / ".venv"

    if reinstall and venv_dir.exists():
        ui.info(i18n.t("steps.common.removing_venv"))
        shutil.rmtree(venv_dir)

    if not venv_dir.exists():
        ui.info(i18n.t("steps.common.creating_venv"))
        if subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=False).returncode != 0:
            ui.error(i18n.t("steps.common.venv_create_failed"))
            return False

    python = detect.venv_python_path(venv_dir)
    ui.info(i18n.t("steps.cli.installing"))
    subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=False
    )
    result = subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", "-e", "."], cwd=cli_dir, check=False
    )
    if result.returncode != 0:
        ui.error(i18n.t("steps.cli.install_failed"))
        return False

    ui.ok(i18n.t("steps.cli.done"))
    return True
