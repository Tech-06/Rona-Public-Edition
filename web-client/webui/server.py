import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from webui import frontend_build, host, i18n, proxy
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
# freely cacheable.
_INDEX_HTML_HEADERS = {"Cache-Control": "no-cache"}


def _localized_index_html() -> str | None:
    """The built SPA's index.html with its default language baked in:
    ``<html lang="...">`` (the initial, pre-hydration value; the SPA's own
    LanguageProvider corrects it once mounted, the same way it already
    does for the dark/light class) and a ``window.__RONA_LANG__`` the
    LanguageProvider reads as its fallback when the viewer's browser has
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
            f'<head>\n    <script>window.__RONA_LANG__ = "{language}";</script>',
            1,
        )
        _index_html_cache = (mtime, content)
    return _index_html_cache[1]


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts or ["localhost"])
    app.add_middleware(CsrfGuardMiddleware)

    app.include_router(host.router)

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

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            content = _localized_index_html()
            if content is not None:
                return HTMLResponse(content, headers=_INDEX_HTML_HEADERS)
            return JSONResponse({"detail": i18n.t("webui.frontend_not_built")}, status_code=404)

    return app


app = create_app()
