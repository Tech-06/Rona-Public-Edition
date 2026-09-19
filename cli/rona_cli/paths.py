"""Locate a Rona installation root and derive every component's paths from it.

The CLI is installed into its own virtualenv (``cli/.venv``) and is meant to
keep working from any working directory once it's on ``PATH`` -- so it can't
assume it's being run from inside the repo. Root resolution order:

1. ``--root`` passed on the command line (handled by the caller; not this
   module) or the ``RONA_HOME`` environment variable.
2. ``root`` recorded in ``~/.rona/config.json`` (written by the installer).
3. Walking up from this file's own location, looking for a folder that
   contains both ``backend/`` and ``web-client/``.
4. The same upward walk from the current working directory.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


class RonaNotFoundError(RuntimeError):
    """Raised when no Rona installation root could be resolved."""


def _looks_like_root(path: Path) -> bool:
    return (path / "backend").is_dir() and (path / "web-client").is_dir()


def state_file() -> Path:
    return Path.home() / ".rona" / "config.json"


def _root_from_state() -> Path | None:
    path = state_file()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    root = data.get("root")
    if not root:
        return None
    candidate = Path(root)
    return candidate if _looks_like_root(candidate) else None


def _search_upward(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if _looks_like_root(candidate):
            return candidate
    return None


def find_root(explicit: str | Path | None = None) -> Path:
    """Resolve the Rona installation root, or raise ``RonaNotFoundError``."""
    if explicit:
        candidate = Path(explicit).resolve()
        if _looks_like_root(candidate):
            return candidate
        raise RonaNotFoundError(
            f"'{candidate}' bir Rona kurulumu gibi görünmüyor "
            "(backend/ ve web-client/ alt klasörleri bekleniyor)."
        )

    env_root = os.environ.get("RONA_HOME")
    if env_root:
        candidate = Path(env_root).resolve()
        if _looks_like_root(candidate):
            return candidate

    state_root = _root_from_state()
    if state_root is not None:
        return state_root

    file_root = _search_upward(Path(__file__).resolve().parent)
    if file_root is not None:
        return file_root

    cwd_root = _search_upward(Path.cwd())
    if cwd_root is not None:
        return cwd_root

    raise RonaNotFoundError(
        "Rona kurulumu bulunamadı. `rona --root <yol>` ile belirt, "
        "RONA_HOME ortam değişkenini ayarla ya da kurulum scriptini çalıştır."
    )


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        candidate = venv_dir / "Scripts" / "python.exe"
    else:
        candidate = venv_dir / "bin" / "python"
    if not candidate.is_file():
        raise RonaNotFoundError(
            f"Sanal ortam bulunamadı: {venv_dir}. Kurulum scriptini çalıştır "
            "ya da elle oluştur."
        )
    return candidate


class RonaPaths:
    """All component paths derived from one resolved installation root."""

    def __init__(self, root: Path):
        self.root = root
        self.backend_dir = root / "backend"
        self.web_dir = root / "web-client"

        self.backend_env = self.backend_dir / ".env"
        self.web_env = self.web_dir / ".env"

        self.backend_db = self.backend_dir / "rona.db"
        self.backend_log = self.backend_dir / "rona.log"
        self.backend_pid = self.backend_dir / "rona.pid"

        self.installed_packages_lockfile = (
            self.backend_dir / "toolbox" / "custom" / "installed.json"
        )

    def backend_python(self) -> Path:
        return _venv_python(self.backend_dir / ".venv")

    def web_python(self) -> Path:
        return _venv_python(self.web_dir / ".venv")
