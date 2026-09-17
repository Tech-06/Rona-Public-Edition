import subprocess
import sys
from pathlib import Path

import uvicorn

from app.config import get_settings

settings = get_settings()


def _autostart_web_client() -> None:
    web_client_dir = (Path(__file__).resolve().parent / settings.web_client_dir).resolve()
    if not web_client_dir.is_dir():
        print(f"[run] WEB_AUTOSTART is set but {web_client_dir} was not found; skipping.")
        return
    kwargs: dict = {"cwd": web_client_dir}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, "-m", "webui", "start"], **kwargs)  # noqa: ASYNC220


if __name__ == "__main__":
    if settings.web_autostart:
        _autostart_web_client()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        timeout_graceful_shutdown=20,
    )
