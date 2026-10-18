from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
VALID_UI_LANGUAGES = {"tr", "en"}
VALID_COOKIE_SECURE = {"auto", "true", "false"}


class Settings(BaseSettings):
    """Standalone settings for the web dashboard.

    Deliberately independent from the backend's own Settings class: this
    service can be deployed and configured without importing anything from
    the backend package. `backend_dir` only feeds the optional local
    process-supervision/log-tail/db-read conveniences (see host.py, db.py) —
    it assumes the backend is checked out as a sibling folder, and those
    features degrade gracefully when it isn't.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    log_level: str = "INFO"
    # The dashboard's default language: the SPA's initial <html lang> and
    # <meta name="rona-lang"> (see webui/server.py's SPA fallback), and the
    # language of this BFF's own user-facing strings (webui/i18n.py). A
    # viewer's own choice, saved in their browser, overrides this without
    # touching the setting -- see AppearanceSection.tsx on the frontend.
    ui_language: str = "tr"

    # Same minimum as the backend's own AUTH_TOKEN check -- the two must match.
    auth_token: str = Field(min_length=32)

    # Dashboard login (see webui/auth.py). The hash is written by
    # `rona web password` / the installer, never by hand; the session secret
    # signs the login cookie and is rotated together with the password.
    web_password_hash: str = ""
    web_session_secret: str = ""
    web_session_days: int = 30
    # "auto" marks the cookie Secure when the request came in over HTTPS
    # (directly or via X-Forwarded-Proto from a tunnel/reverse proxy).
    web_cookie_secure: str = "auto"

    web_host: str = "127.0.0.1"
    web_port: int = 8016
    backend_url: str = "http://127.0.0.1:8000"
    web_allowed_hosts: str = "localhost,127.0.0.1"

    backend_dir: str = "../backend"
    backend_log_file: str = "rona.log"

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in VALID_LOG_LEVELS:
            raise ValueError(f"invalid log level: {value!r}")
        return normalized

    @field_validator("web_cookie_secure")
    @classmethod
    def validate_web_cookie_secure(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in VALID_COOKIE_SECURE:
            raise ValueError(f"invalid web_cookie_secure: {value!r}")
        return normalized

    @field_validator("ui_language")
    @classmethod
    def validate_ui_language(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in VALID_UI_LANGUAGES:
            raise ValueError(f"invalid ui_language: {value!r}")
        return normalized


@lru_cache
def get_settings() -> Settings:
    return Settings()
