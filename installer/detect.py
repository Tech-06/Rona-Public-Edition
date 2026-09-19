"""OS / package-manager / prerequisite / existing-install detection.

Python itself is not detected here -- by the time this module runs, the
bootstrap script (install.ps1/install.sh) has already guaranteed a 3.11+
interpreter is what's executing us (``python_version()`` below just
reports on it).
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal

OSName = Literal["windows", "macos", "linux"]


def detect_os() -> OSName:
    system = platform.system()
    if system == "Windows":
        return "windows"
    if system == "Darwin":
        return "macos"
    return "linux"


def python_version() -> tuple[int, int, int]:
    """The version of the interpreter currently running the installer."""
    return sys.version_info[:3]


def _run_text(cmd: list[str]) -> str | None:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stdout or "") + (result.stderr or "")
    return output.strip() or None


def node_version() -> tuple[int, int, int] | None:
    path = shutil.which("node")
    if not path:
        return None
    output = _run_text([path, "--version"])
    if not output:
        return None
    text = output.strip().lstrip("v")
    parts = text.split(".")
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2].split("-")[0]))
    except (IndexError, ValueError):
        return None


def git_available() -> bool:
    return shutil.which("git") is not None


def package_manager(os_name: OSName) -> str | None:
    if os_name == "windows":
        return "winget" if shutil.which("winget") else None
    if os_name == "macos":
        return "brew" if shutil.which("brew") else None
    for candidate in ("apt-get", "dnf", "pacman"):
        if shutil.which(candidate):
            return candidate
    return None


def venv_python_path(venv_dir: Path) -> Path:
    if platform.system() == "Windows":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


class InstalledComponents:
    """What already exists on disk for each component -- used only to
    label the selection menu and decide whether a step should wipe an
    existing .venv first; it never affects correctness of a fresh run."""

    def __init__(self, root: Path):
        self.root = root
        cli_dir = root / "cli"
        backend_dir = root / "backend"
        web_dir = root / "web-client"

        self.cli = venv_python_path(cli_dir / ".venv").is_file()
        self.backend = venv_python_path(backend_dir / ".venv").is_file() and (
            backend_dir / ".env"
        ).is_file()
        self.web = (
            venv_python_path(web_dir / ".venv").is_file()
            and (web_dir / ".env").is_file()
            and (web_dir / "webui" / "dist" / "index.html").is_file()
        )

    def as_dict(self) -> dict[str, bool]:
        return {"cli": self.cli, "backend": self.backend, "web": self.web}
