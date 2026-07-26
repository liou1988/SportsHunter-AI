from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "SportsHunter-AI"
    environment: str = "production"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    database_url: str = "sqlite:///./sports_hunter.db"
    log_level: str = "INFO"
    log_file: Path = Path("logs/sports_hunter.log")
    timezone: str = "Asia/Shanghai"

    enabled_sports: list[str] = Field(default_factory=lambda: ["football"])
    enable_scheduler: bool = True
    enable_demo_feed: bool = False

    data_provider: str = "free"
    football_data_source: str = "free"
    football_data_season: int | None = 2026
    free_provider_base_url: str = "https://site.api.espn.com"
    free_provider_football_leagues: list[str] = Field(
        default_factory=lambda: ["eng.1", "esp.1", "ita.1", "ger.1", "fra.1", "uefa.champions"]
    )

    provider_timeout_seconds: float = 10.0
    provider_retry_attempts: int = 3
    provider_retry_backoff_seconds: float = 0.5
    provider_cache_ttl_seconds: int = 180
    provider_rate_limit_per_minute: int = 60

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_push_enabled: bool = False

    history_collection_enabled: bool = True
    evaluation_enabled: bool = True
    automation_enabled: bool = True
    reports_dir: Path = Path("reports")
    system_status_path: Path = Path("system_status.md")
    validation_report_path: Path = Path("validation_report.md")

    @field_validator("enabled_sports", "free_provider_football_leagues", mode="before")
    @classmethod
    def parse_csv_list(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return list(value)

    @field_validator("telegram_bot_token", "telegram_chat_id", mode="before")
    @classmethod
    def empty_string_to_none(cls, value: Any) -> Any:
        if value == "":
            return None
        return value

    @field_validator("football_data_season", mode="before")
    @classmethod
    def empty_season_uses_default(cls, value: Any) -> int | None:
        if value is None or value == "":
            return 2026
        return int(value)

    def ensure_runtime_dirs(self) -> None:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
