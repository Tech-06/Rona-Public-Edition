"""Install step: the web dashboard (web-client/.venv + requirements +
.env skeleton + npm ci/install + npm run build).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from installer import detect, envgen, ui


def install(root: Path, *, reinstall: bool) -> bool:
    ui.step("Web paneli")
    web_dir = root / "web-client"
    frontend_dir = web_dir / "frontend"
    venv_dir = web_dir / ".venv"

    if reinstall and venv_dir.exists():
        ui.info("Var olan sanal ortam kaldırılıyor...")
        shutil.rmtree(venv_dir)

    if not venv_dir.exists():
        ui.info("Sanal ortam oluşturuluyor...")
        if subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=False).returncode != 0:
            ui.error("Sanal ortam oluşturulamadı.")
            return False

    python = detect.venv_python_path(venv_dir)
    ui.info("Bağımlılıklar kuruluyor...")
    subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=False
    )
    result = subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", "-r", "requirements.txt"],
        cwd=web_dir,
        check=False,
    )
    if result.returncode != 0:
        ui.error("Bağımlılık kurulumu başarısız oldu.")
        return False

    envgen.materialize_env(web_dir / ".env.example", web_dir / ".env")

    npm = shutil.which("npm")
    if npm is None:
        ui.error("npm bulunamadı; web paneli derlenemedi.")
        return False

    on_windows = sys.platform == "win32"
    lockfile = frontend_dir / "package-lock.json"
    npm_install_cmd = [npm, "ci"] if lockfile.exists() else [npm, "install"]
    ui.info(f"Frontend bağımlılıkları kuruluyor ({' '.join(npm_install_cmd)})...")
    result = subprocess.run(npm_install_cmd, cwd=frontend_dir, check=False, shell=on_windows)
    if result.returncode != 0:
        ui.error("npm install/ci başarısız oldu.")
        return False

    ui.info("Frontend derleniyor (npm run build)...")
    result = subprocess.run([npm, "run", "build"], cwd=frontend_dir, check=False, shell=on_windows)
    if result.returncode != 0:
        ui.error("npm run build başarısız oldu.")
        return False

    ui.ok("Web paneli kuruldu.")
    return True
