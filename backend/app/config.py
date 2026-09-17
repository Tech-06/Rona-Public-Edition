import json
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Rona"

    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = True
    log_level: str = "INFO"
    log_file: str = "rona.log"

    auth_token: str

    flash_model: str
    flash_model_url: str
    flash_model_api: str
    flash_model_headers: dict[str, str] = {}

    pro_model: str = ""
    pro_model_url: str = ""
    pro_model_api: str = ""
    pro_model_headers: dict[str, str] = {}

    conversation_ttl_seconds: int = 7200
    max_history_messages: int = 50
    llm_timeout_seconds: int = 120
    graph_recursion_limit: int = 100

    subagent_max_rounds: int = 50
    subagent_timeout_seconds: int = 1800
    subagent_max_concurrent: int = 3
    subagent_retention_hours: int = 24
    subagent_llm_timeout_seconds: int = 300
    subagent_max_context_messages: int = 40

    trigger_timezone: str = "UTC"
    trigger_max_concurrent: int = 2
    trigger_max_rounds: int = 30
    trigger_llm_timeout_seconds: int = 300
    trigger_max_context_messages: int = 30

    # Whether this process should spawn the web dashboard as a subprocess on
    # startup (see run.py). The dashboard's own host/port/allowed-hosts are
    # configured independently in its own .env now that it's a separate
    # deployable component.
    web_autostart: bool = False
    web_client_dir: str = "../web-client"

    @property
    def pro_configured(self) -> bool:
        return bool(self.pro_model and self.pro_model_url and self.pro_model_api)

    @field_validator("flash_model_headers", "pro_model_headers", mode="before")
    @classmethod
    def parse_model_headers(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return {}
            return json.loads(value)
        return value

    @field_validator("flash_model_url", "pro_model_url")
    @classmethod
    def normalize_model_url(cls, value: str) -> str:
        value = value.rstrip("/")
        suffix = "/chat/completions"
        value = value.removesuffix(suffix)
        return value

    @field_validator("trigger_timezone")
    @classmethod
    def validate_trigger_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"invalid IANA timezone: {value!r}") from exc
        return value

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
