"""Install step: the web dashboard (web-client/.venv + requirements +
.env skeleton + npm ci/install + npm run build).
"""

from __future__ import annotations

import getpass
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

from rona_cli import envio, webauth

from installer import detect, envgen, i18n, ui

PASSWORD_ATTEMPTS = 3


def _ask_password() -> str | None:
    """A confirmed panel password, or None to skip (empty input, EOF, or
    three failed attempts). Re-prompts on mismatch / too short."""
    for _ in range(PASSWORD_ATTEMPTS):
        try:
            first = getpass.getpass(i18n.t("steps.web.password_prompt"))
            if not first:
                return None
            second = getpass.getpass(i18n.t("steps.web.password_confirm_prompt"))
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if first != second:
            ui.warn(i18n.t("steps.web.password_mismatch"))
        elif len(first) < webauth.MIN_PASSWORD_LENGTH:
            ui.warn(i18n.t("steps.web.password_too_short", min=webauth.MIN_PASSWORD_LENGTH))
        else:
            return first
    return None


def _ensure_panel_password(env_path: Path) -> None:
    """The dashboard has no web-side "first password" screen (behind a tunnel
    every visitor looks like loopback), so the password has to come from here
    or from `rona web password`. Never overwrites an existing one."""
    if envio.read_env_file(env_path).get("WEB_PASSWORD_HASH"):
        return
    hint = i18n.t("steps.web.password_later_hint")
    if not sys.stdin.isatty():
        ui.info(hint)
        return
    ui.info(i18n.t("steps.web.password_intro"))
    password = _ask_password()
    if password is None:
        ui.info(hint)
        return
    envio.write_env_updates(
        env_path,
        {
            "WEB_PASSWORD_HASH": webauth.hash_password(password),
            "WEB_SESSION_SECRET": secrets.token_urlsafe(32),
        },
    )
    ui.ok(i18n.t("steps.web.password_set"))


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
    _ensure_panel_password(web_dir / ".env")

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
