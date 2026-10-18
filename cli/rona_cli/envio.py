"""Small, dependency-free helpers for safely editing a ``.env`` file in place.

Independent stdlib copy of ``backend/toolbox/envfile.py``'s behaviour (same
semantics: in-place replace, append new keys, ``.bak`` snapshot, atomic
replace via a temp file). Kept separate on purpose -- the CLI must not import
the backend's own ``toolbox`` package (see ``web-client/tests/
test_webui_isolation.py`` for the sibling rule this project follows).
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class EnvValueError(ValueError):
    """A key or value that cannot be written to a .env file safely."""


def _validate_key(key: str) -> None:
    if not isinstance(key, str) or not _KEY_RE.match(key):
        raise EnvValueError(f"invalid .env key {key!r}: must match [A-Za-z_][A-Za-z0-9_]*")


def validate_env_updates(updates: dict[str, str]) -> None:
    """Reject anything that could inject extra lines; the value is never echoed."""
    for key, value in updates.items():
        _validate_key(key)
        if not isinstance(value, str) or any(ch in value for ch in ("\r", "\n", "\x00")):
            raise EnvValueError(
                f"invalid value for {key}: must be a string without CR, LF or NUL characters"
            )


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
    validate_env_updates(updates)
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
    """Delete the given keys' lines entirely from the .env file, if present."""
    keys = set(keys)
    for key in keys:
        _validate_key(key)
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
        bak = path.with_suffix(".bak")
        fd = os.open(bak, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(path.read_bytes())
        try:
            os.chmod(bak, 0o600)
        except OSError:
            pass
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".env.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
