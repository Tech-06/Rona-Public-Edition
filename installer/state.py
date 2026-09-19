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


def write_state(root: Path, components: dict[str, bool]) -> None:
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "root": str(root),
        "version": __version__,
        "components": components,
        "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platform": platform.system(),
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_state() -> dict[str, Any] | None:
    path = state_file()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
