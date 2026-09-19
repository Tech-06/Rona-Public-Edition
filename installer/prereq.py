"""Detect and (with confirmation) install missing prerequisites: currently
just Node.js, needed only when the web dashboard is selected (its build
step runs npm). Python itself is the bootstrap script's job, not this
module's -- by the time this runs, Python 3.11+ is already guaranteed.
"""

from __future__ import annotations

import shutil
import subprocess

from installer import i18n, ui

_WINGET_IDS = {"node": "OpenJS.NodeJS.LTS", "git": "Git.Git"}
_APT_PACKAGES = {"node": ["nodejs", "npm"], "git": ["git"]}
_DNF_PACKAGES = {"node": ["nodejs", "npm"], "git": ["git"]}
_PACMAN_PACKAGES = {"node": ["nodejs", "npm"], "git": ["git"]}
_BREW_PACKAGES = {"node": ["node"], "git": ["git"]}


def install_command(os_name: str, pkg_manager: str | None, package: str) -> list[str] | None:
    if os_name == "windows":
        winget_id = _WINGET_IDS.get(package)
        return ["winget", "install", "--id", winget_id, "-e", "--source", "winget"] if winget_id else None
    if os_name == "macos":
        names = _BREW_PACKAGES.get(package)
        return ["brew", "install", *names] if names else None
    if pkg_manager == "apt-get":
        names = _APT_PACKAGES.get(package)
        return ["sudo", "apt-get", "install", "-y", *names] if names else None
    if pkg_manager == "dnf":
        names = _DNF_PACKAGES.get(package)
        return ["sudo", "dnf", "install", "-y", *names] if names else None
    if pkg_manager == "pacman":
        names = _PACMAN_PACKAGES.get(package)
        return ["sudo", "pacman", "-S", "--noconfirm", *names] if names else None
    return None


def ensure_prerequisite(
    name: str,
    package: str,
    available: bool,
    os_name: str,
    pkg_manager: str | None,
    auto_yes: bool,
) -> bool:
    """Returns True if the prerequisite is (now) available."""
    if available:
        return True

    command = install_command(os_name, pkg_manager, package)
    if command is None:
        ui.error(i18n.t("prereq.no_package_manager", name=name))
        ui.info(i18n.t("prereq.install_manually", name=name))
        return False

    ui.warn(i18n.t("prereq.not_found", name=name))
    ui.info(i18n.t("prereq.will_run", command=" ".join(command)))
    if not auto_yes and not ui.confirm(i18n.t("prereq.confirm_install", name=name), default=True):
        ui.info(i18n.t("common.cancelled"))
        return False

    try:
        result = subprocess.run(command, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        ui.error(i18n.t("prereq.install_failed_exc", name=name, exc=exc))
        return False
    if result.returncode != 0:
        ui.error(i18n.t("prereq.install_failed_code", name=name, code=result.returncode))
        return False

    ui.ok(i18n.t("prereq.installed_ok", name=name))
    if shutil.which(package) is None:
        ui.warn(i18n.t("prereq.installed_not_on_path", name=name))
        return False
    return True
