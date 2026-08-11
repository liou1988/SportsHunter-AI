from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from types import UnionType
from typing import Any, Union, get_args, get_origin

from pydantic import Field, field_validator
from pydantic_core import PydanticUndefined
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


_UNHANDLED = object()
DEFAULT_FREE_PROVIDER_SOURCES = ["espn", "thesportsdb"]
DEFAULT_FREE_FOOTBALL_LEAGUES = [
    "eng.1",
    "eng.2",
    "eng.3",
    "eng.4",
    "eng.5",
    "eng.fa",
    "eng.fa_qual",
    "eng.league_cup",
    "eng.trophy",
    "eng.charity",
    "esp.1",
    "esp.2",
    "esp.copa_del_rey",
    "esp.super_cup",
    "ita.1",
    "ita.2",
    "ita.coppa_italia",
    "ita.super_cup",
    "ger.1",
    "ger.2",
    "ger.dfb_pokal",
    "ger.super_cup",
    "fra.1",
    "fra.2",
    "fra.coupe_de_france",
    "fra.super_cup",
    "por.1",
    "por.taca.portugal",
    "ned.1",
    "ned.2",
    "ned.cup",
    "ned.supercup",
    "sco.1",
    "sco.2",
    "sco.tennents",
    "sco.cis",
    "sco.challenge",
    "bel.1",
    "sui.1",
    "aut.1",
    "den.1",
    "nor.1",
    "swe.1",
    "pol.1",
    "tur.1",
    "gre.1",
    "rus.1",
    "uefa.champions",
    "uefa.champions_qual",
    "uefa.europa",
    "uefa.europa_qual",
    "uefa.europa.conf",
    "uefa.europa.conf_qual",
    "uefa.super_cup",
    "uefa.nations",
    "uefa.euro",
    "uefa.euroq",
    "fifa.world",
    "fifa.wwc",
    "fifa.cwc",
    "fifa.worldq.uefa",
    "fifa.worldq.conmebol",
    "fifa.worldq.concacaf",
    "fifa.worldq.afc",
    "fifa.worldq.caf",
    "fifa.worldq.ofc",
    "fifa.friendly",
    "fifa.friendly.w",
    "fifa.friendly_u21",
    "fifa.world.u20",
    "fifa.world.u17",
    "club.friendly",
    "nonfifa",
    "conmebol.libertadores",
    "conmebol.sudamericana",
    "conmebol.america",
    "concacaf.champions",
    "concacaf.champions_cup",
    "concacaf.gold",
    "concacaf.nations.league",
    "afc.champions",
    "afc.cup",
    "afc.asian.cup",
    "aff.championship",
    "caf.champions",
    "caf.confed",
    "caf.w.nations",
    "kor.1",
    "kor.2",
    "jpn.1",
    "jpn.2",
    "aus.1",
    "chn.1",
    "idn.1",
    "tha.1",
    "sgp.1",
    "ind.1",
    "ind.2",
    "ksa.1",
    "isr.1",
    "rsa.1",
    "bra.1",
    "bra.2",
    "bra.copa_do_brazil",
    "bra.camp.carioca",
    "bra.camp.paulista",
    "bra.camp.gaucho",
    "bra.camp.mineiro",
    "arg.1",
    "arg.2",
    "arg.3",
    "arg.copa",
    "usa.1",
    "usa.nwsl",
    "usa.open",
    "usa.usl.1",
    "usa.usl.l1",
    "mex.1",
    "mex.2",
    "col.1",
    "col.copa",
    "ecu.1",
    "per.1",
    "uru.1",
    "uru.2",
    "chi.1",
    "par.1",
    "bol.1",
    "ven.1",
    "hon.1",
    "crc.1",
    "gua.1",
    "slv.1",
]


def _is_optional(annotation: Any) -> bool:
    origin = get_origin(annotation)
    return origin in {Union, UnionType} and type(None) in get_args(annotation)


def _strip_optional(annotation: Any) -> Any:
    if not _is_optional(annotation):
        return annotation
    return next(arg for arg in get_args(annotation) if arg is not type(None))


def _field_default(field: Any) -> Any:
    default_factory = getattr(field, "default_factory", None)
    if default_factory is not None:
        return default_factory()
    default = getattr(field, "default", PydanticUndefined)
    if default is not PydanticUndefined:
        return default
    return None


def _coerce_env_value(field: Any, value: str) -> Any:
    annotation = field.annotation
    bare_annotation = _strip_optional(annotation)
    origin = get_origin(bare_annotation)

    if origin is list and get_args(bare_annotation) in {(str,), ()}:
        normalized = value.strip()
        if normalized == "":
            return _field_default(field)
        if normalized.startswith("["):
            loaded = json.loads(normalized)
            return [str(item).strip() for item in loaded if str(item).strip()]
        return [item.strip() for item in normalized.split(",") if item.strip()]

    if value == "":
        if _is_optional(annotation):
            return _field_default(field)
        if bare_annotation in {bool, int, float}:
            return _field_default(field)

    if bare_annotation is bool:
        lowered = value.strip().lower()
        if lowered in {"1", "true", "t", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "f", "no", "n", "off"}:
            return False

    if bare_annotation is int:
        return int(value)

    if bare_annotation is float:
        return float(value)

    return _UNHANDLED


class SportsHunterEnvSettingsSource(EnvSettingsSource):
    def prepare_field_value(self, field_name: str, field: Any, value: Any, value_is_complex: bool) -> Any:
        if isinstance(value, str):
            coerced = _coerce_env_value(field, value)
            if coerced is not _UNHANDLED:
                return coerced
        return super().prepare_field_value(field_name, field, value, value_is_complex)


class SportsHunterDotEnvSettingsSource(DotEnvSettingsSource):
    def prepare_field_value(self, field_name: str, field: Any, value: Any, value_is_complex: bool) -> Any:
        if isinstance(value, str):
            coerced = _coerce_env_value(field, value)
            if coerced is not _UNHANDLED:
                return coerced
        return super().prepare_field_value(field_name, field, value, value_is_complex)


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
    free_provider_sources: list[str] = Field(default_factory=lambda: DEFAULT_FREE_PROVIDER_SOURCES.copy())
    free_provider_base_url: str = "https://site.api.espn.com"
    free_provider_thesportsdb_base_url: str = "https://www.thesportsdb.com/api/v1/json/3"
    free_provider_football_leagues: list[str] = Field(default_factory=lambda: DEFAULT_FREE_FOOTBALL_LEAGUES.copy())
    odds_aggregator_enabled: bool = False
    odds_aggregator_provider: str = "the_odds_api"
    the_odds_api_key: str | None = None
    the_odds_api_base_url: str = "https://api.the-odds-api.com"
    the_odds_api_regions: list[str] = Field(default_factory=lambda: ["uk", "eu"])
    the_odds_api_bookmakers: list[str] = Field(default_factory=list)
    the_odds_api_markets: list[str] = Field(default_factory=lambda: ["h2h", "spreads", "totals"])
    api_football_key: str | None = None
    api_football_base_url: str = "https://v3.football.api-sports.io"
    api_football_live_odds_enabled: bool = True
    api_football_live_include_prematch: bool = False
    api_football_prematch_window_minutes: int = 90
    api_football_prematch_grace_minutes: int = 10
    api_football_prematch_cache_ttl_seconds: int = 1800
    api_football_live_cache_ttl_seconds: int = 300
    api_football_bookmaker_ids: list[str] = Field(default_factory=list)
    api_football_bet_ids: list[str] = Field(default_factory=list)
    api_football_odds_max_pages: int = 1

    provider_timeout_seconds: float = 10.0
    provider_retry_attempts: int = 3
    provider_retry_backoff_seconds: float = 0.5
    provider_cache_ttl_seconds: int = 180
    provider_rate_limit_per_minute: int = 60

    telegram_enabled: bool = False
    bot_token: str | None = None
    chat_id: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_push_enabled: bool = False
    telegram_alert_signals: list[str] = Field(default_factory=lambda: ["STRONG_BUY", "BUY", "WATCH"])
    telegram_alert_interval_minutes: int = 5
    telegram_alert_retention_days: int = 7
    telegram_alert_archive_path: Path = Path("reports/telegram_alerts.json")

    recommendation_gate_enabled: bool = True
    recommendation_allowed_signals: list[str] = Field(default_factory=lambda: ["WATCH", "BUY", "STRONG_BUY"])
    recommendation_min_score: float = 62.0
    recommendation_min_confidence: float = 0.60
    recommendation_prematch_min_minutes: int = 15
    recommendation_prematch_max_minutes: int = 360
    recommendation_require_odds: bool = True
    recommendation_require_fresh_odds: bool = True
    recommendation_max_odds_age_minutes: int = 120
    recommendation_min_bookmakers: int = 1
    recommendation_require_sharp_anchor: bool = False
    recommendation_min_market_edge: float = 0.04
    recommendation_min_expected_value: float = 0.0
    recommendation_league_review_days: int = 15
    recommendation_league_min_samples: int = 20
    recommendation_league_min_hit_rate: float = 0.40
    recommendation_league_min_roi: float = -0.30

    history_collection_enabled: bool = True
    evaluation_enabled: bool = True
    automation_enabled: bool = True
    model_optimizer_enabled: bool = True
    model_optimizer_check_hour: int = 1
    model_optimizer_check_minute: int = 20
    model_optimizer_manual_min_samples: int = 20
    model_optimizer_auto_apply_enabled: bool = True
    model_optimizer_auto_apply_min_samples: int = 100
    model_optimizer_status_path: Path = Path("reports/model_optimizer_status.json")
    reports_dir: Path = Path("reports")
    system_status_path: Path = Path("system_status.md")
    validation_report_path: Path = Path("validation_report.md")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            SportsHunterEnvSettingsSource(
                settings_cls,
                case_sensitive=getattr(env_settings, "case_sensitive", None),
                env_prefix=getattr(env_settings, "env_prefix", None),
                env_nested_delimiter=getattr(env_settings, "env_nested_delimiter", None),
                env_nested_max_split=getattr(env_settings, "env_nested_max_split", None),
                env_ignore_empty=getattr(env_settings, "env_ignore_empty", None),
                env_parse_none_str=getattr(env_settings, "env_parse_none_str", None),
                env_parse_enums=getattr(env_settings, "env_parse_enums", None),
            ),
            SportsHunterDotEnvSettingsSource(
                settings_cls,
                env_file=getattr(dotenv_settings, "env_file", None),
                env_file_encoding=getattr(dotenv_settings, "env_file_encoding", None),
                dotenv_filtering=getattr(dotenv_settings, "dotenv_filtering", None),
                case_sensitive=getattr(dotenv_settings, "case_sensitive", None),
                env_prefix=getattr(dotenv_settings, "env_prefix", None),
                env_nested_delimiter=getattr(dotenv_settings, "env_nested_delimiter", None),
                env_nested_max_split=getattr(dotenv_settings, "env_nested_max_split", None),
                env_ignore_empty=getattr(dotenv_settings, "env_ignore_empty", None),
                env_parse_none_str=getattr(dotenv_settings, "env_parse_none_str", None),
                env_parse_enums=getattr(dotenv_settings, "env_parse_enums", None),
            ),
            file_secret_settings,
        )

    @field_validator(
        "enabled_sports",
        "free_provider_sources",
        "free_provider_football_leagues",
        "the_odds_api_regions",
        "the_odds_api_bookmakers",
        "the_odds_api_markets",
        "api_football_bookmaker_ids",
        "api_football_bet_ids",
        "telegram_alert_signals",
        "recommendation_allowed_signals",
        mode="before",
    )
    @classmethod
    def parse_csv_list(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return list(value)

    @field_validator(
        "bot_token",
        "chat_id",
        "telegram_bot_token",
        "telegram_chat_id",
        "the_odds_api_key",
        "api_football_key",
        mode="before",
    )
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

    @property
    def telegram_is_enabled(self) -> bool:
        return self.telegram_enabled or self.telegram_push_enabled

    @property
    def telegram_effective_bot_token(self) -> str | None:
        return self.bot_token or self.telegram_bot_token

    @property
    def telegram_effective_chat_id(self) -> str | None:
        return self.chat_id or self.telegram_chat_id


@lru_cache
def get_settings() -> Settings:
    return Settings()
