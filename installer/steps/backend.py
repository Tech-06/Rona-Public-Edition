"""Install step: the backend (backend/.venv + requirements + .env skeleton
+ create_db.py). AUTH_TOKEN generation is handled centrally by
installer/main.py, since it must match web-client/.env too.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from installer import detect, envgen, ui


def install(root: Path, *, reinstall: bool) -> bool:
    ui.step("Backend")
    backend_dir = root / "backend"
    venv_dir = backend_dir / ".venv"

    if reinstall and venv_dir.exists():
        ui.info("Var olan sanal ortam kaldırılıyor...")
        shutil.rmtree(venv_dir)

    if not venv_dir.exists():
        ui.info("Sanal ortam oluşturuluyor...")
        if subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=False).returncode != 0:
            ui.error("Sanal ortam oluşturulamadı.")
            return False

    python = detect.venv_python_path(venv_dir)
    ui.info("Bağımlılıklar kuruluyor (bu biraz sürebilir)...")
    subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=False
    )
    result = subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", "-r", "requirements.txt"],
        cwd=backend_dir,
        check=False,
    )
    if result.returncode != 0:
        ui.error("Bağımlılık kurulumu başarısız oldu.")
        return False

    envgen.materialize_env(backend_dir / ".env.example", backend_dir / ".env")

    ui.info("Veritabanı hazırlanıyor...")
    result = subprocess.run([str(python), "create_db.py"], cwd=backend_dir, check=False)
    if result.returncode != 0:
        ui.error("Veritabanı hazırlığı başarısız oldu.")
        return False

    ui.ok("Backend kuruldu.")
    return True
