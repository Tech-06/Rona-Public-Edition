from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


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

    auth_token: str

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
