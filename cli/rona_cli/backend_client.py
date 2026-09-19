"""Shared helper for CLI commands that must talk to a *running* backend
(`rona edit memory`, `rona task`, `rona log list`/`show`/`del`) -- as
opposed to `rona edit model`/`auth`, which edit `.env` directly and never
need the backend to be up.
"""

from __future__ import annotations

from rona_cli import envio, http, i18n
from rona_cli.paths import RonaPaths


class BackendUnavailable(RuntimeError):
    """Raised when the backend's .env is unconfigured or it isn't reachable."""


def _env_host_port(env: dict[str, str]) -> tuple[str, int]:
    host = env.get("HOST", "0.0.0.0") or "0.0.0.0"
    if host in ("0.0.0.0", ""):
        host = "127.0.0.1"
    try:
        port = int(env.get("PORT", "8000") or "8000")
    except ValueError:
        port = 8000
    return host, port


def backend_client(paths: RonaPaths, *, timeout: float = 10.0) -> http.Client:
    """Build an authenticated client for the backend, or raise
    `BackendUnavailable` with a message telling the user what to do."""
    env = envio.read_env_file(paths.backend_env)
    token = env.get("AUTH_TOKEN", "")
    if not token:
        raise BackendUnavailable(i18n.t("backend_client.no_auth_token"))
    host, port = _env_host_port(env)
    return http.Client(base_url=f"http://{host}:{port}", token=token, timeout=timeout)


def require_running(client: http.Client) -> None:
    """Raise `BackendUnavailable` if a quick /health probe fails."""
    try:
        client.get("/health", timeout=3.0)
    except http.ApiError as exc:
        raise BackendUnavailable(i18n.t("backend_client.unreachable", exc=exc)) from exc
