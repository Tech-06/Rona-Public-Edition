"""~/.rona/config.json -- lightweight installer state.

Read by ``rona_cli.paths.find_root`` as one of its root-resolution
fallbacks, so `rona` keeps working from any directory once installed.
"""

from __future__ import annotations

import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__version__ = "0.1.0"


def state_file() -> Path:
    return Path.home() / ".rona" / "config.json"


def write_state(root: Path, components: dict[str, bool], *, language: str | None = None) -> None:
    """Merges onto whatever's already in ``~/.rona/config.json`` rather
    than overwriting it outright -- something else may have written a
    field there first (most notably `rona edit lang`, which can run
    before this installer ever has: install just the CLI via pip, run
    `rona edit lang en --cli`, then later run the installer to add the
    other components. Wiping that choice on the next `write_state()` call
    would be a surprising regression).
    """
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
    data: dict[str, Any] = {
        **existing,
        "root": str(root),
        "version": __version__,
        "components": components,
        "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platform": platform.system(),
    }
    if language is not None:
        data["language"] = language
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_state() -> dict[str, Any] | None:
    path = state_file()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
