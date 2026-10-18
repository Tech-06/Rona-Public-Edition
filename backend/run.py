import ipaddress
import os
import subprocess
import sys
from pathlib import Path

import uvicorn

import i18n
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


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


if __name__ == "__main__":
    # Files the backend creates (DBs, logs, package state) are private.
    if os.name != "nt":
        os.umask(0o077)
    tls_options: dict = {}
    if settings.ssl_certfile and settings.ssl_keyfile:
        tls_options = {
            "ssl_certfile": settings.ssl_certfile,
            "ssl_keyfile": settings.ssl_keyfile,
        }
    elif not _is_loopback(settings.host):
        print(i18n.t("run.insecure_exposure", host=settings.host))
    if settings.web_autostart:
        _autostart_web_client()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        timeout_graceful_shutdown=20,
        **tls_options,
    )
