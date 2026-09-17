import uvicorn

from app.config import get_settings

settings = get_settings()

if __name__ == "__main__":
    if settings.web_autostart:
        from webui import supervisor

        supervisor.start()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        timeout_graceful_shutdown=20,
    )
