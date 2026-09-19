"""AUTH_TOKEN generation and .env.example -> .env materialization.

Reuses ``rona_cli.envio`` (added to sys.path by installer/main.py) for the
actual safe read/write -- pure stdlib, no dependency on cli/.venv existing
yet, and it guarantees a value written here behaves identically to one
written later by `rona edit`.
"""

from __future__ import annotations

import secrets
import shutil
from pathlib import Path

from rona_cli import envio

TOKEN_BYTES = 32


def generate_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def materialize_env(example_path: Path, env_path: Path) -> None:
    """Seed ``env_path`` from ``example_path`` (copying comments and
    structure intact) if it doesn't exist yet.

    Re-running the installer against an already-configured component
    leaves the existing file completely untouched -- this is also what
    keeps a repair/reinstall from losing previously-entered API keys.
    """
    if env_path.exists():
        return
    if example_path.exists():
        shutil.copy(example_path, env_path)
    else:
        env_path.write_text("", encoding="utf-8")


def ensure_auth_token(root: Path, *, install_web: bool) -> str:
    """Make sure backend/.env has an AUTH_TOKEN, and (if the web dashboard
    is part of this run) that web-client/.env holds the identical value --
    they must match exactly (see app/main.py's bearer check and
    webui/proxy.py, which injects it into every proxied request).

    Reuses an existing token rather than generating a new one when
    backend/.env already has one, so re-running the installer never
    invalidates an already-configured, already-running setup.
    """
    backend_env = root / "backend" / ".env"
    web_env = root / "web-client" / ".env"

    current = envio.read_env_file(backend_env).get("AUTH_TOKEN", "") if backend_env.exists() else ""
    token = current or generate_token()

    envio.write_env_updates(backend_env, {"AUTH_TOKEN": token})
    if install_web:
        envio.write_env_updates(web_env, {"AUTH_TOKEN": token})
    return token
