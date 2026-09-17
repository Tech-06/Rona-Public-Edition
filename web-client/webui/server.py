import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from webui import host, proxy
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
                return JSONResponse({"detail": "Unsupported content type"}, status_code=415)
            fetch_site = request.headers.get("sec-fetch-site")
            if fetch_site not in (None, "same-origin", "none"):
                return JSONResponse({"detail": "Cross-site request blocked"}, status_code=403)
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
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
            index = DIST_DIR / "index.html"
            if index.is_file():
                return FileResponse(index)
            return JSONResponse({"detail": "Frontend not built"}, status_code=404)

    return app


app = create_app()
