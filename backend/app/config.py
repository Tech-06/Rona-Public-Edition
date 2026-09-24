import json
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
VALID_LANGUAGES = {"tr", "en"}


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
    # Rona's own speaking language (the persona prompt's directive), plus
    # every backend-authored string a human actually sees: HTTPException
    # details, stored task/subagent run outcomes, and log lines. See
    # i18n.py's module docstring for what this deliberately does *not*
    # cover (tool-facing error strings, forwarded exception text).
    language: str = "tr"

    auth_token: str

    flash_model: str
    flash_model_url: str
    flash_model_api: str
    flash_model_headers: dict[str, str] = {}

    pro_model: str = ""
    pro_model_url: str = ""
    pro_model_api: str = ""
    pro_model_headers: dict[str, str] = {}

    conversation_ttl_seconds: int = 0
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

    # Memory lifecycle ("Konsolidasyon", backend/memory/): automatic
    # promotion short -> seasonal -> deep by recall count, seasonal
    # archiving after a long idle period, and deletion of rarely-recalled
    # short-layer memories. Each mechanism can be switched off on its own;
    # interval 0 disables the automatic run entirely (a manual run is still
    # always possible). See backend/memory/policy.py for how these become
    # a MemoryPolicy.
    memory_consolidation_interval_hours: int = Field(24, ge=0)  # 0 = no automatic runs
    memory_auto_promote_enabled: bool = True
    memory_auto_archive_enabled: bool = True
    memory_auto_delete_enabled: bool = True
    memory_short_promote_hits: int = Field(3, ge=1)
    memory_seasonal_promote_hits: int = Field(10, ge=1)
    memory_seasonal_archive_days: int = Field(90, ge=1)
    memory_short_delete_days: int = Field(7, ge=1)
    memory_short_delete_below_hits: int = Field(3, ge=1)
    memory_access_top_n: int = Field(3, ge=1)
    memory_access_cooldown_hours: int = Field(12, ge=0)

    # Whether this process should spawn the web dashboard as a subprocess on
    # startup (see run.py). The dashboard's own host/port/allowed-hosts are
    # configured independently in its own .env now that it's a separate
    # deployable component.
    web_autostart: bool = False
    web_client_dir: str = "../web-client"

    @property
    def pro_configured(self) -> bool:
        # A model is configured once it has a name and a URL. The api key is
        # deliberately not part of the test: a gateway may authenticate on a
        # custom header instead (see app/llm.py), and requiring a key here
        # silently disabled a Pro model that was set up perfectly well.
        return bool(self.pro_model and self.pro_model_url)

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

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in VALID_LANGUAGES:
            raise ValueError(f"invalid language: {value!r}")
        return normalized


@lru_cache
def get_settings() -> Settings:
    return Settings()
