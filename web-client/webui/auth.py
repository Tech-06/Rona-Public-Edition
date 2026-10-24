"""Password login + signed session cookie for the dashboard.

Why this exists: webui/proxy.py injects the backend's bearer token into every
proxied request, so whoever can reach this port would otherwise control the
whole backend and the /host/* admin routes. Everything but the static SPA
shell therefore needs a valid ``rona_session`` cookie (see RequireSession).

There is deliberately no web endpoint that sets the *first* password: behind
a tunnel or reverse proxy every client looks like loopback, so "first visitor
wins" would hand the panel to a stranger. The first password comes from
``rona web password`` or the installer, which write WEB_PASSWORD_HASH to
web-client/.env; this module re-reads that file when it changes (and it
outranks the process environment for these two values), so a new password
takes effect without restarting the dashboard.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import asyncio
import ipaddress
import json
import logging
import os
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from webui import envwrite, i18n
from webui.config import get_settings

logger = logging.getLogger("uvicorn.error")
router = APIRouter(prefix="/auth")

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

COOKIE_NAME = "rona_session"
MIN_PASSWORD_LENGTH = 4
# Longer inputs are rejected before hashing so a huge body can't be used to
# burn CPU/memory in scrypt.
MAX_PASSWORD_LENGTH = 1024

SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SALT_BYTES = 16
# n=2**15, r=8 needs ~32 MiB, exactly hashlib's default cap, which rejects it.
SCRYPT_MAXMEM = 64 * 1024 * 1024

MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 300
_MAX_TRACKED_CLIENTS = 1024
# Each scrypt run takes ~32 MiB; without a cap, a burst of parallel login
# requests (the failure counter only grows after each hash finishes) could
# exhaust memory. Two at a time is plenty for a single-user panel.
_SCRYPT_SLOTS = 2
_scrypt_semaphore: asyncio.Semaphore | None = None


# -- password hashing ---------------------------------------------------------


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """``scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>``. ``salt`` is only for the
    fixed test vector shared with cli/rona_cli/webauth.py."""
    salt = secrets.token_bytes(SALT_BYTES) if salt is None else salt
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
        maxmem=SCRYPT_MAXMEM,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check; a malformed ``stored`` string is just ``False``."""
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = _unb64(hash_b64)
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_unb64(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
            maxmem=SCRYPT_MAXMEM,
        )
        return hmac.compare_digest(digest, expected)
    except Exception:
        return False


# -- credentials (web-client/.env > env > Settings) ----------------------------

# (path, mtime_ns, parsed values): re-parsed only when the file changes.
_env_cache: tuple[Path, int, dict[str, str]] | None = None
_ephemeral_secret: str | None = None


def _env_file_values() -> dict[str, str]:
    global _env_cache
    path = ENV_PATH
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return {}
    if _env_cache is None or _env_cache[0] != path or _env_cache[1] != mtime:
        try:
            _env_cache = (path, mtime, envwrite.read_env_file(path))
        except (OSError, UnicodeDecodeError):
            return {}
    return _env_cache[2]


def _credential(name: str, fallback: str) -> str:
    # The .env file wins over the process environment on purpose: under the
    # shipped systemd unit (EnvironmentFile=.env) these two values are frozen
    # in os.environ at start, while `rona web password` and POST /auth/password
    # only rewrite the file. Preferring the environment would keep the old
    # password working and reject the new one until a restart.
    value = _env_file_values().get(name, "").strip()
    if value:
        return value
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    return fallback


def password_hash() -> str:
    return _credential("WEB_PASSWORD_HASH", get_settings().web_password_hash)


def session_secret() -> str:
    """The cookie-signing key. Without a configured one, a random per-process
    key is used (one warning), so sessions simply don't survive a restart."""
    global _ephemeral_secret
    secret = _credential("WEB_SESSION_SECRET", get_settings().web_session_secret)
    if secret:
        return secret
    if _ephemeral_secret is None:
        _ephemeral_secret = secrets.token_urlsafe(32)
        logger.warning(i18n.t("webui.session_secret_ephemeral"))
    return _ephemeral_secret


# -- session cookie -------------------------------------------------------------


def _password_version(stored_hash: str) -> str:
    # Changing the password changes the hash (fresh salt), which invalidates
    # every cookie signed against the old one.
    return hashlib.sha256(stored_hash.encode("utf-8")).hexdigest()[:16]


def _sign(secret: str, payload_b64: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256)
    return _b64(mac.digest())


def make_session_token(
    stored_hash: str, secret: str, *, days: int, now: float | None = None
) -> str:
    now = time.time() if now is None else now
    payload = {"exp": int(now + days * 86400), "pv": _password_version(stored_hash)}
    payload_b64 = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{payload_b64}.{_sign(secret, payload_b64)}"


def verify_session_token(
    token: str | None, stored_hash: str, secret: str, *, now: float | None = None
) -> bool:
    if not token or not stored_hash:
        return False
    try:
        payload_b64, _, signature = token.partition(".")
        if not hmac.compare_digest(signature, _sign(secret, payload_b64)):
            return False
        payload = json.loads(_unb64(payload_b64))
        now = time.time() if now is None else now
        return (
            isinstance(payload["exp"], (int, float))
            and payload["exp"] > now
            and hmac.compare_digest(str(payload["pv"]), _password_version(stored_hash))
        )
    except Exception:
        return False


def is_authenticated(request: Request) -> bool:
    return verify_session_token(
        request.cookies.get(COOKIE_NAME), password_hash(), session_secret()
    )


def _cookie_secure(request: Request) -> bool:
    mode = get_settings().web_cookie_secure
    if mode == "true":
        return True
    if mode == "false":
        return False
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return request.url.scheme == "https" or forwarded == "https"


def _set_session_cookie(response: JSONResponse, request: Request) -> None:
    days = get_settings().web_session_days
    response.set_cookie(
        COOKIE_NAME,
        make_session_token(password_hash(), session_secret(), days=days),
        max_age=days * 86400,
        path="/",
        httponly=True,
        samesite="strict",
        secure=_cookie_secure(request),
    )


# -- login rate limit -----------------------------------------------------------

# client ip -> timestamps of recent failures. In-memory on purpose: a restart
# resets it, which only matters to someone who can already restart the panel.
_failures: dict[str, list[float]] = {}


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _prune(now: float) -> None:
    cutoff = now - FAILURE_WINDOW_SECONDS
    for key in list(_failures):
        recent = [t for t in _failures[key] if t > cutoff]
        if recent:
            _failures[key] = recent
        else:
            del _failures[key]
    while len(_failures) > _MAX_TRACKED_CLIENTS:
        del _failures[next(iter(_failures))]


def _retry_after(key: str, now: float) -> int:
    """Seconds until ``key`` may try again, or 0 if it isn't locked out."""
    _prune(now)
    recent = _failures.get(key, [])
    if len(recent) < MAX_FAILURES:
        return 0
    return max(1, int(recent[0] + FAILURE_WINDOW_SECONDS - now) + 1)


def _record_failure(key: str, now: float) -> None:
    _failures.setdefault(key, []).append(now)
    _prune(now)


def _reserve_attempt(key: str, now: float) -> int:
    """Check the lockout and, if free, count this attempt as a failure *before*
    hashing. Otherwise a burst of parallel guesses all pass the check while the
    scrypt semaphore queues them, and none gets rate limited. Returns the
    retry-after seconds (0 = go ahead); a successful login clears the entry."""
    wait = _retry_after(key, now)
    if wait:
        return wait
    _record_failure(key, now)
    return 0


def _release_attempt(key: str, now: float) -> None:
    """Un-count a reservation whose password turned out to be correct."""
    recent = _failures.get(key)
    if recent and now in recent:
        recent.remove(now)
        if not recent:
            del _failures[key]


def _too_many(seconds: int) -> JSONResponse:
    return JSONResponse(
        {
            "detail": i18n.t("webui.too_many_attempts", seconds=seconds),
            "code": "too_many_attempts",
            "retry_after": seconds,
        },
        status_code=429,
        headers={"Retry-After": str(seconds)},
    )


def _error(status: int, code: str, key: str, **kwargs: object) -> JSONResponse:
    return JSONResponse({"detail": i18n.t(key, **kwargs), "code": code}, status_code=status)


async def _verify_limited(password: str, stored: str) -> bool:
    global _scrypt_semaphore
    if len(password) > MAX_PASSWORD_LENGTH:
        return False
    if _scrypt_semaphore is None:
        _scrypt_semaphore = asyncio.Semaphore(_SCRYPT_SLOTS)
    async with _scrypt_semaphore:
        return await run_in_threadpool(verify_password, password, stored)


# -- routes ---------------------------------------------------------------------


class LoginBody(BaseModel):
    password: str


class PasswordBody(BaseModel):
    current: str
    new: str


@router.get("/status")
async def auth_status(request: Request):
    return {"authenticated": is_authenticated(request), "password_set": bool(password_hash())}


@router.post("/login")
async def login(body: LoginBody, request: Request):
    stored = password_hash()
    if not stored:
        return _error(409, "password_not_set", "webui.password_not_set")
    key = _client_key(request)
    now = time.time()
    wait = _reserve_attempt(key, now)
    if wait:
        return _too_many(wait)
    ok = await _verify_limited(body.password, stored)
    if not ok:
        return _error(401, "invalid_password", "webui.invalid_password")
    _failures.pop(key, None)
    response = JSONResponse({"authenticated": True})
    _set_session_cookie(response, request)
    return response


@router.post("/logout")
async def logout():
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="strict")
    return response


@router.post("/password")
async def change_password(body: PasswordBody, request: Request):
    if not is_authenticated(request):
        return _error(401, "login_required", "webui.login_required")
    key = _client_key(request)
    now = time.time()
    wait = _reserve_attempt(key, now)
    if wait:
        return _too_many(wait)
    ok = await _verify_limited(body.current, password_hash())
    if not ok:
        return _error(401, "invalid_password", "webui.password_wrong_current")
    # The current password was right; a bad new one isn't a guessing attempt.
    _release_attempt(key, now)
    if not MIN_PASSWORD_LENGTH <= len(body.new) <= MAX_PASSWORD_LENGTH:
        return _error(
            400, "password_too_short", "webui.password_too_short", min=MIN_PASSWORD_LENGTH
        )
    new_hash = await run_in_threadpool(hash_password, body.new)
    try:
        envwrite.write_env_updates(
            ENV_PATH,
            {"WEB_PASSWORD_HASH": new_hash, "WEB_SESSION_SECRET": secrets.token_urlsafe(32)},
        )
    except (OSError, envwrite.EnvValueError):
        logger.exception("could not write the new web password to .env")
        return _error(500, "password_write_failed", "webui.password_write_failed")
    _failures.pop(key, None)
    response = JSONResponse({"ok": True})
    _set_session_cookie(response, request)
    return response


# -- middleware -----------------------------------------------------------------


def requires_session(path: str) -> bool:
    """Everything that reaches the backend or controls this host. The SPA shell
    and its static files stay public so the login screen can load."""
    if path == "/host/healthz":
        return False
    return (
        path == "/health"
        or path == "/chat"
        or path.startswith(("/api/", "/chat/", "/host/"))
        or path in ("/api", "/host")
    )


class RequireSessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if requires_session(request.url.path) and not is_authenticated(request):
            return _error(401, "login_required", "webui.login_required")
        return await call_next(request)


# -- startup guard --------------------------------------------------------------


def is_loopback_host(host: str) -> bool:
    host = host.strip().strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_startup(web_host: str) -> None:
    """Refuse to serve an unlocked panel beyond loopback; on loopback just warn."""
    if password_hash():
        return
    if not is_loopback_host(web_host):
        raise RuntimeError(i18n.t("webui.public_without_password", host=web_host))
    logger.warning(i18n.t("webui.panel_locked_warning"))
