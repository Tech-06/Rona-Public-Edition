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


_WILDCARD_HOSTS = frozenset({"", "0.0.0.0", "::", "[::]"})


def env_host_port(env: dict[str, str]) -> tuple[str, int]:
    """Connectable (host, port) for the backend described by ``env``.

    A wildcard bind address is not something a client can dial, so it maps to
    loopback.
    """
    host = (env.get("HOST", "0.0.0.0") or "0.0.0.0").strip()
    if host in _WILDCARD_HOSTS:
        host = "127.0.0.1"
    try:
        port = int(env.get("PORT", "8000") or "8000")
    except ValueError:
        port = 8000
    return host, port


def tls_enabled(env: dict[str, str]) -> bool:
    """The backend serves TLS only when both SSL keys are set (see run.py)."""
    return bool(env.get("SSL_CERTFILE", "").strip() and env.get("SSL_KEYFILE", "").strip())


def backend_base_url(env: dict[str, str]) -> str:
    """Single place that builds the backend URL: scheme follows the SSL keys,
    and IPv6 literals are bracketed."""
    host, port = env_host_port(env)
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    scheme = "https" if tls_enabled(env) else "http"
    return f"{scheme}://{host}:{port}"


def make_client(env: dict[str, str], *, token: str | None, timeout: float) -> http.Client:
    """Client for the backend in ``env``. A self-signed certificate is the norm
    for a local backend, so verification is skipped for loopback hosts only;
    a remote HTTPS backend keeps normal certificate checks."""
    url = backend_base_url(env)
    ctx = http.unverified_context() if url.startswith("https://") and http.is_loopback_url(url) else None
    return http.Client(base_url=url, token=token, timeout=timeout, ssl_context=ctx)


def backend_client(paths: RonaPaths, *, timeout: float = 10.0) -> http.Client:
    """Build an authenticated client for the backend, or raise
    `BackendUnavailable` with a message telling the user what to do."""
    env = envio.read_env_file(paths.backend_env)
    token = env.get("AUTH_TOKEN", "")
    if not token:
        raise BackendUnavailable(i18n.t("backend_client.no_auth_token"))
    return make_client(env, token=token, timeout=timeout)


def require_running(client: http.Client) -> None:
    """Raise `BackendUnavailable` if a quick /health probe fails."""
    try:
        client.get("/health", timeout=3.0)
    except http.ApiError as exc:
        raise BackendUnavailable(i18n.t("backend_client.unreachable", exc=exc)) from exc
