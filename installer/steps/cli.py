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

from installer import detect, ui


def install(root: Path, *, reinstall: bool) -> bool:
    ui.step("CLI (rona)")
    cli_dir = root / "cli"
    venv_dir = cli_dir / ".venv"

    if reinstall and venv_dir.exists():
        ui.info("Var olan sanal ortam kaldırılıyor...")
        shutil.rmtree(venv_dir)

    if not venv_dir.exists():
        ui.info("Sanal ortam oluşturuluyor...")
        if subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=False).returncode != 0:
            ui.error("Sanal ortam oluşturulamadı.")
            return False

    python = detect.venv_python_path(venv_dir)
    ui.info("rona-cli kuruluyor (pip install -e .)...")
    subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=False
    )
    result = subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", "-e", "."], cwd=cli_dir, check=False
    )
    if result.returncode != 0:
        ui.error("rona-cli kurulumu başarısız oldu.")
        return False

    ui.ok("rona CLI kuruldu.")
    return True
