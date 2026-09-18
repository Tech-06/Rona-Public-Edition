"""Small, dependency-free helpers for safely editing a ``.env`` file in place.

Shared by ``toolbox.manager`` (writing a custom package's secret config) so
its rollback path and the settings dashboard's config editor go through the
same safe-write behaviour: a ``.bak`` snapshot before overwriting, and an
atomic replace via a temp file.
"""

from __future__ import annotations

import os
from pathlib import Path


def read_env_file(path: Path) -> dict[str, str]:
    """Parse ``KEY=value`` lines from a .env file. Missing file -> ``{}``."""
    pairs: dict[str, str] = {}
    if not path.exists():
        return pairs
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition("=")
        pairs[key.strip()] = value
    return pairs


def write_env_updates(path: Path, updates: dict[str, str]) -> None:
    """Set each ``KEY=value`` in the .env file at ``path``.

    Existing keys are replaced in place (comments and unrelated lines are
    left untouched); new keys are appended. The previous file is copied to
    ``path`` + ``.bak`` first, and the new content is written atomically
    (temp file + ``os.replace``).
    """
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.partition("=")[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        new_lines.append(line)
    for key, value in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={value}")
    _atomic_write(path, "\n".join(new_lines) + "\n")


def remove_env_keys(path: Path, keys) -> None:
    """Delete the given keys' lines entirely from the .env file, if present.

    Used to undo a rollback-worthy install: a key that did not exist before
    the install wrote it should not survive as an orphaned line afterwards.
    """
    keys = set(keys)
    if not keys or not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()

    def _is_removable(line: str) -> bool:
        return (
            "=" in line
            and not line.lstrip().startswith("#")
            and line.partition("=")[0].strip() in keys
        )

    new_lines = [line for line in lines if not _is_removable(line)]
    if len(new_lines) == len(lines):
        return
    text = "\n".join(new_lines) + ("\n" if new_lines else "")
    _atomic_write(path, text)


def _atomic_write(path: Path, text: str) -> None:
    if path.exists():
        path.with_suffix(".bak").write_bytes(path.read_bytes())
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
