import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from webui import auth, frontend_build, host, i18n, package_jobs, proxy
from webui.config import get_settings
from webui.logging_config import configure_file_logging

settings = get_settings()

ROOT_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = Path(__file__).resolve().parent / "dist"
PID_PATH = ROOT_DIR / "webui.pid"

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class CsrfGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method not in _SAFE_METHODS:
            content_type = request.headers.get("content-type", "")
            if "application/json" not in content_type:
                return JSONResponse({"detail": i18n.t("webui.unsupported_content_type")}, status_code=415)
            fetch_site = request.headers.get("sec-fetch-site")
            if fetch_site not in (None, "same-origin", "none"):
                return JSONResponse({"detail": i18n.t("webui.cross_site_blocked")}, status_code=403)
        return await call_next(request)


_INDEX_HTML_LANG_RE = re.compile(r'<html lang="[^"]*">')
# (index.html's mtime when it was read, the localized content)
_index_html_cache: tuple[float, str] | None = None

# index.html is the one file that names the current build's hashed asset
# files, so browsers must revalidate it on every load -- otherwise a phone
# can keep running an old bundle for as long as its cache sees fit, long
# after the server was rebuilt. The hashed /assets/* files themselves stay
# freely cacheable. The same reasoning applies to every other file the SPA
# fallback serves by name below (manifest.webmanifest, sw.js, ...): none of
# them are content-hashed, so they all get the same no-cache treatment.
_NO_CACHE_HEADERS = {"Cache-Control": "no-cache"}

# Root-level files `npm run build` copies from frontend/public/ verbatim
# (see vite.config.ts -- public/ is Vite's default, untouched-by-the-bundler
# static dir). Only these exact names are ever served from DIST_DIR's root;
# `spa_fallback` below rejects everything else, including a path that
# merely resolves onto the same directory (FastAPI's `path` converter
# never yields `..` segments, so there is no traversal to guard against
# beyond this whitelist).
_ROOT_FILES = {
    "manifest.webmanifest": "application/manifest+json",
    "sw.js": "text/javascript",
    "offline.html": "text/html",
    "offline.js": "text/javascript",
    "theme-init.js": "text/javascript",
    "favicon.svg": "image/svg+xml",
}


def _root_static_file(full_path: str) -> FileResponse | None:
    media_type = _ROOT_FILES.get(full_path)
    if media_type is None:
        return None
    file_path = DIST_DIR / full_path
    if not file_path.is_file():
        return None
    return FileResponse(file_path, media_type=media_type, headers=_NO_CACHE_HEADERS)


# One policy for every response (SPA, static, /api proxy, /auth, errors).
# `style-src 'unsafe-inline'` stays because React style props and
# theme-init.js set inline styles; scripts are strictly same-origin, and
# img-src/connect-src have no remote hosts, so a prompt-injected markdown
# image can't beacon data out even if the sanitizer is bypassed.
_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
    "manifest-src 'self'; worker-src 'self'; object-src 'none'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
_SECURITY_HEADERS = {
    "Content-Security-Policy": _CSP,
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


class SecurityHeadersMiddleware:
    """Pure ASGI (not BaseHTTPMiddleware) so streaming/SSE responses from
    the proxy pass through untouched. Existing headers win (setdefault)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in _SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _localized_index_html() -> str | None:
    """The built SPA's index.html with its default language baked in:
    ``<html lang="...">`` (the initial, pre-hydration value; the SPA's own
    LanguageProvider corrects it once mounted, the same way it already
    does for the dark/light class) and a ``<meta name="rona-lang">`` the
    LanguageProvider reads as its fallback (a meta tag, not an inline
    script, so the CSP can keep ``script-src 'self'``) when the viewer's browser has
    no stored preference yet. UI_LANGUAGE doesn't change without a
    restart (Settings is lru_cache'd), so the result is cached -- but keyed
    on index.html's mtime, so an `npm run build` while this process keeps
    running is picked up on the next request instead of serving an
    index.html whose hashed asset files the rebuild just deleted.
    """
    global _index_html_cache
    index_path = DIST_DIR / "index.html"
    if not index_path.is_file():
        return None
    mtime = index_path.stat().st_mtime
    if _index_html_cache is None or _index_html_cache[0] != mtime:
        content = index_path.read_text(encoding="utf-8")
        language = get_settings().ui_language
        content = _INDEX_HTML_LANG_RE.sub(f'<html lang="{language}">', content, count=1)
        content = content.replace(
            "<head>",
            f'<head>\n    <meta name="rona-lang" content="{language}" />',
            1,
        )
        _index_html_cache = (mtime, content)
    return _index_html_cache[1]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Before anything is written or served: a panel reachable beyond
    # loopback with no password configured must not come up at all.
    auth.check_startup(settings.web_host)
    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
    if frontend_build.is_stale():
        logging.getLogger("uvicorn.error").warning(i18n.t("webui.frontend_stale"))
    yield
    try:
        PID_PATH.unlink()
    except OSError:
        pass


def create_app() -> FastAPI:
    configure_file_logging(settings.log_level)
    app = FastAPI(title="Rona Web", lifespan=lifespan)

    allowed_hosts = [h.strip() for h in settings.web_allowed_hosts.split(",") if h.strip()]
    # Starlette runs the last-added middleware first: TrustedHost (outermost)
    # -> CsrfGuard -> RequireSession, so a login-less request is still
    # rejected for a bad Host / content type before the session is looked at.
    app.add_middleware(auth.RequireSessionMiddleware)
    app.add_middleware(CsrfGuardMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts or ["localhost"])
    # Added last = outermost: the headers also land on TrustedHost's 400,
    # CsrfGuard's 403 and RequireSession's 401, not just on app responses.
    app.add_middleware(SecurityHeadersMiddleware)

    app.include_router(auth.router)
    app.include_router(host.router)
    app.include_router(package_jobs.router)

    @app.api_route(
        "/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"]
    )
    async def api_proxy(path: str, request: Request):
        return await proxy.proxy_request(request, f"/api/{path}")

    @app.post("/chat")
    async def chat_proxy(request: Request):
        return await proxy.proxy_request(request, "/chat")

    @app.post("/chat/stream")
    async def chat_stream_proxy(request: Request):
        return await proxy.proxy_request(request, "/chat/stream")

    @app.get("/health")
    async def health_proxy(request: Request):
        return await proxy.proxy_request(request, "/health")

    if DIST_DIR.is_dir():
        assets_dir = DIST_DIR / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
        icons_dir = DIST_DIR / "icons"
        if icons_dir.is_dir():
            app.mount("/icons", StaticFiles(directory=icons_dir), name="icons")

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            root_file = _root_static_file(full_path)
            if root_file is not None:
                return root_file
            content = _localized_index_html()
            if content is not None:
                return HTMLResponse(content, headers=_NO_CACHE_HEADERS)
            return JSONResponse({"detail": i18n.t("webui.frontend_not_built")}, status_code=404)

    return app


app = create_app()
