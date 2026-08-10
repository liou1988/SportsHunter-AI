from __future__ import annotations

import csv
import json
import sqlite3
from io import StringIO
from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.main import app
from config.settings import Settings
from config.logging import LOG_FILE_BACKUP_COUNT, LOG_FILE_MAX_BYTES, SensitiveDataFilter
from database.base import Base
from database.models import LearningRecord, MatchResult, ModelVersion, OddsSnapshot, Prediction
from database.repositories import DashboardRepository, SportsRepository
from database.session import _configure_sqlite_connection, _engine_kwargs
from datahub.hub import DataHub
from datahub.models import Fixture, FixtureStatus, League, Odds, OddsMarket, Score, Standing, Team
from datahub.odds_aggregator import ApiFootballOddsProvider
from datahub.providers.mock import MockProvider
from data_sync import engine as data_sync_engine
from data_sync.models import SyncSummary
from core.rating.engine import HunterRatingEngine
from core.risk.models import RiskBreakdown, RiskLevel, RiskReason
from core.signal.models import Signal
from core.signal.rules import decide_signal
from core.signal.strategy import SIGNAL_STRATEGY
from evaluation.dataset import EvaluationDataset
from evaluation.metrics import calculate_metrics
from evaluation.models import EvaluationReport
from evaluation.runner import EvaluationRunner
from evaluation.settlement import SettlementService
from optimizer.engine import ModelOptimizer
from optimizer import scheduler as optimizer_scheduler
from optimizer.weights import load_active_rating_weights
from pipeline.archive import PredictionArchive
from pipeline.runner import PredictionPipeline
from pipeline.market_model import MarketPredictionModel
from pipeline.models import HandicapPrediction, MarketPrediction, ScorePrediction, TotalGoalsPrediction
from pipeline.recommendation_gate import RecommendationGate
from pipeline.probability import (
    HistoricalProbabilityModel,
    OutcomeProbabilities,
    ProbabilityProjection,
    ScoreProbability,
)
from free_provider.football import FreeFootballProvider, LEAGUE_NAMES
from features.models import FeatureVector
from features.pipeline import FeatureBuilder
from api import dependencies
from api.services.recommendations import (
    build_archived_recommendations,
    build_recommendations_export_csv,
    build_today_recommendations,
)
from api.routers import provider as provider_router
from api.routers import recommendations as recommendations_router
from api.routers import telegram as telegram_router
from dashboard.router import get_datahub as dashboard_get_datahub
from dashboard import service as dashboard_service
from scheduler import jobs
from scheduler.runner import create_scheduler
from telegram_bot import localization as localization_module
from telegram_bot.alerts import AlertArchive, RecommendationAlertPusher, format_recommendation_alert_message
from telegram_bot.fixtures import format_fixtures_message
from telegram_bot.localization import translate_match_text, translate_team_name
from telegram_bot.notifier import TelegramNotifier, TelegramSendResult
from telegram_bot.bot import command_help_text, format_alert_push_reply, format_status_message
from telegram_bot.recommendations import format_recommendations_message


def test_settings_accept_empty_football_season() -> None:
    settings = Settings(football_data_season="", _env_file=None)
    assert settings.football_data_season == 2026


def test_settings_parse_single_enabled_sport_from_env(monkeypatch) -> None:
    monkeypatch.setenv("ENABLED_SPORTS", "football")
    settings = Settings(_env_file=None)
    assert settings.enabled_sports == ["football"]


def test_settings_parse_csv_enabled_sports_from_env(monkeypatch) -> None:
    monkeypatch.setenv("ENABLED_SPORTS", "football,basketball,tennis")
    settings = Settings(_env_file=None)
    assert settings.enabled_sports == ["football", "basketball", "tennis"]


def test_settings_parse_json_enabled_sports_from_env(monkeypatch) -> None:
    monkeypatch.setenv("ENABLED_SPORTS", '["football","basketball"]')
    settings = Settings(_env_file=None)
    assert settings.enabled_sports == ["football", "basketball"]


def test_settings_parse_empty_optional_int_bool_and_float_env(monkeypatch) -> None:
    monkeypatch.setenv("FOOTBALL_DATA_SEASON", "")
    monkeypatch.setenv("ENABLE_SCHEDULER", "off")
    monkeypatch.setenv("PROVIDER_TIMEOUT_SECONDS", "2.5")
    settings = Settings(_env_file=None)
    assert settings.football_data_season == 2026
    assert settings.enable_scheduler is False
    assert settings.provider_timeout_seconds == 2.5


def test_settings_parse_telegram_env_aliases(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("BOT_TOKEN", "token-value")
    monkeypatch.setenv("CHAT_ID", "chat-value")
    settings = Settings(_env_file=None)
    assert settings.telegram_is_enabled is True
    assert settings.telegram_effective_bot_token == "token-value"
    assert settings.telegram_effective_chat_id == "chat-value"


def test_sqlite_engine_uses_busy_timeout_connect_args() -> None:
    assert _engine_kwargs("sqlite:///./sports_hunter.db") == {
        "connect_args": {"check_same_thread": False, "timeout": 30}
    }
    assert _engine_kwargs("postgresql+psycopg://user:pass@db/sportshunter") == {}


def test_sqlite_connection_pragmas_enable_concurrent_runtime(tmp_path) -> None:
    connection = sqlite3.connect(tmp_path / "sports_hunter.db")
    try:
        _configure_sqlite_connection(connection, None)
        cursor = connection.cursor()
        try:
            journal_mode = cursor.execute("PRAGMA journal_mode").fetchone()[0]
            synchronous = cursor.execute("PRAGMA synchronous").fetchone()[0]
            busy_timeout = cursor.execute("PRAGMA busy_timeout").fetchone()[0]
            foreign_keys = cursor.execute("PRAGMA foreign_keys").fetchone()[0]
        finally:
            cursor.close()
    finally:
        connection.close()

    assert journal_mode.lower() == "wal"
    assert synchronous == 1
    assert busy_timeout == 30000
    assert foreign_keys == 1


def test_settings_parse_free_provider_sources(monkeypatch) -> None:
    monkeypatch.setenv("FREE_PROVIDER_SOURCES", "espn,thesportsdb")
    settings = Settings(_env_file=None)
    assert settings.free_provider_sources == ["espn", "thesportsdb"]


def test_settings_parse_odds_aggregator_config(monkeypatch) -> None:
    monkeypatch.setenv("ODDS_AGGREGATOR_ENABLED", "true")
    monkeypatch.setenv("THE_ODDS_API_KEY", "test-key")
    monkeypatch.setenv("THE_ODDS_API_REGIONS", "uk,eu")
    monkeypatch.setenv("THE_ODDS_API_BOOKMAKERS", "pinnacle,betfair_ex_uk")
    settings = Settings(_env_file=None)
    assert settings.odds_aggregator_enabled is True
    assert settings.the_odds_api_key == "test-key"
    assert settings.the_odds_api_regions == ["uk", "eu"]
    assert settings.the_odds_api_bookmakers == ["pinnacle", "betfair_ex_uk"]


def test_settings_parse_api_football_odds_config(monkeypatch) -> None:
    monkeypatch.setenv("ODDS_AGGREGATOR_ENABLED", "true")
    monkeypatch.setenv("ODDS_AGGREGATOR_PROVIDER", "api_football")
    monkeypatch.setenv("API_FOOTBALL_KEY", "test-key")
    monkeypatch.setenv("API_FOOTBALL_LIVE_ODDS_ENABLED", "false")
    monkeypatch.setenv("API_FOOTBALL_LIVE_INCLUDE_PREMATCH", "true")
    monkeypatch.setenv("API_FOOTBALL_PREMATCH_WINDOW_MINUTES", "75")
    monkeypatch.setenv("API_FOOTBALL_PREMATCH_GRACE_MINUTES", "5")
    monkeypatch.setenv("API_FOOTBALL_PREMATCH_CACHE_TTL_SECONDS", "1200")
    monkeypatch.setenv("API_FOOTBALL_LIVE_CACHE_TTL_SECONDS", "180")
    monkeypatch.setenv("API_FOOTBALL_BOOKMAKER_IDS", "6,8")
    monkeypatch.setenv("API_FOOTBALL_BET_IDS", "1,4,5")
    monkeypatch.setenv("API_FOOTBALL_ODDS_MAX_PAGES", "2")
    settings = Settings(_env_file=None)
    assert settings.odds_aggregator_enabled is True
    assert settings.odds_aggregator_provider == "api_football"
    assert settings.api_football_key == "test-key"
    assert settings.api_football_live_odds_enabled is False
    assert settings.api_football_live_include_prematch is True
    assert settings.api_football_prematch_window_minutes == 75
    assert settings.api_football_prematch_grace_minutes == 5
    assert settings.api_football_prematch_cache_ttl_seconds == 1200
    assert settings.api_football_live_cache_ttl_seconds == 180
    assert settings.api_football_bookmaker_ids == ["6", "8"]
    assert settings.api_football_bet_ids == ["1", "4", "5"]
    assert settings.api_football_odds_max_pages == 2


def test_settings_parse_telegram_alert_signals(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_ALERT_SIGNALS", "STRONG_BUY,BUY,WATCH")
    settings = Settings(_env_file=None)
    assert settings.telegram_alert_signals == ["STRONG_BUY", "BUY", "WATCH"]


def test_settings_default_telegram_alert_signals_include_watch() -> None:
    settings = Settings(_env_file=None)
    assert settings.telegram_alert_signals == ["STRONG_BUY", "BUY", "WATCH"]


def test_env_example_defaults_to_free_provider() -> None:
    text = Path(".env.example").read_text(encoding="utf-8")
    assert "DATA_PROVIDER=free" in text
    assert "FOOTBALL_DATA_SOURCE=free" in text
    assert "FOOTBALL_DATA_SEASON=2026" in text
    assert "FREE_PROVIDER_SOURCES=espn,thesportsdb" in text
    assert "FREE_PROVIDER_THESPORTSDB_BASE_URL=https://www.thesportsdb.com/api/v1/json/3" in text
    for league_id in [
        "kor.1",
        "kor.2",
        "jpn.1",
        "jpn.2",
        "aus.1",
        "bra.2",
        "arg.1",
        "usa.1",
        "usa.usl.1",
        "mex.1",
        "uefa.europa.conf",
        "fifa.friendly",
        "club.friendly",
        "aff.championship",
        "caf.w.nations",
        "ecu.1",
        "bol.1",
    ]:
        assert league_id in text


def test_settings_default_free_leagues_include_requested_regions() -> None:
    settings = Settings(_env_file=None)
    expected_leagues = {
        "kor.1",
        "kor.2",
        "jpn.1",
        "jpn.2",
        "aus.1",
        "bra.1",
        "bra.2",
        "arg.1",
        "arg.2",
        "usa.1",
        "mex.1",
        "mex.2",
        "uefa.champions",
        "uefa.europa",
        "uefa.europa.conf",
        "uefa.super_cup",
        "fifa.friendly",
        "club.friendly",
        "aff.championship",
        "caf.w.nations",
        "ecu.1",
        "bol.1",
        "usa.usl.1",
    }
    assert settings.free_provider_sources == ["espn", "thesportsdb"]
    assert expected_leagues.issubset(set(settings.free_provider_football_leagues))
    assert expected_leagues.issubset(set(LEAGUE_NAMES))


def test_docker_compose_allows_telegram_env_override() -> None:
    text = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "TELEGRAM_ENABLED: ${TELEGRAM_ENABLED:-false}" in text
    assert "BOT_TOKEN: ${BOT_TOKEN:-}" in text
    assert "CHAT_ID: ${CHAT_ID:-}" in text
    assert "TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN:-}" in text
    assert "TELEGRAM_CHAT_ID: ${TELEGRAM_CHAT_ID:-}" in text
    assert "TELEGRAM_PUSH_ENABLED: ${TELEGRAM_PUSH_ENABLED:-false}" in text
    assert "TELEGRAM_ALERT_SIGNALS: ${TELEGRAM_ALERT_SIGNALS:-STRONG_BUY,BUY,WATCH}" in text
    assert "TELEGRAM_ALERT_INTERVAL_MINUTES: ${TELEGRAM_ALERT_INTERVAL_MINUTES:-5}" in text
    assert "TELEGRAM_ALERT_ARCHIVE_PATH: ${TELEGRAM_ALERT_ARCHIVE_PATH:-/app/reports/telegram_alerts.json}" in text
    assert "RECOMMENDATION_GATE_ENABLED: ${RECOMMENDATION_GATE_ENABLED:-true}" in text
    assert "RECOMMENDATION_ALLOWED_SIGNALS: ${RECOMMENDATION_ALLOWED_SIGNALS:-STRONG_BUY,BUY}" in text
    assert "RECOMMENDATION_REQUIRE_FRESH_ODDS: ${RECOMMENDATION_REQUIRE_FRESH_ODDS:-true}" in text
    assert "RECOMMENDATION_MAX_ODDS_AGE_MINUTES: ${RECOMMENDATION_MAX_ODDS_AGE_MINUTES:-120}" in text
    assert "RECOMMENDATION_MIN_BOOKMAKERS: ${RECOMMENDATION_MIN_BOOKMAKERS:-1}" in text
    assert "RECOMMENDATION_REQUIRE_SHARP_ANCHOR: ${RECOMMENDATION_REQUIRE_SHARP_ANCHOR:-false}" in text
    assert "RECOMMENDATION_MIN_MARKET_EDGE: ${RECOMMENDATION_MIN_MARKET_EDGE:-0.04}" in text
    assert "MODEL_OPTIMIZER_ENABLED: ${MODEL_OPTIMIZER_ENABLED:-true}" in text
    assert "MODEL_OPTIMIZER_CHECK_HOUR: ${MODEL_OPTIMIZER_CHECK_HOUR:-1}" in text
    assert "MODEL_OPTIMIZER_CHECK_MINUTE: ${MODEL_OPTIMIZER_CHECK_MINUTE:-20}" in text
    assert "MODEL_OPTIMIZER_AUTO_APPLY_ENABLED: ${MODEL_OPTIMIZER_AUTO_APPLY_ENABLED:-true}" in text
    assert "MODEL_OPTIMIZER_AUTO_APPLY_MIN_SAMPLES: ${MODEL_OPTIMIZER_AUTO_APPLY_MIN_SAMPLES:-100}" in text
    assert text.count('max-size: "10m"') == 2
    assert text.count('max-file: "3"') == 2


def test_env_example_contains_triggered_alert_settings() -> None:
    text = Path(".env.example").read_text(encoding="utf-8")
    assert "ODDS_AGGREGATOR_ENABLED=false" in text
    assert "ODDS_AGGREGATOR_PROVIDER=the_odds_api" in text
    assert "THE_ODDS_API_KEY=" in text
    assert "THE_ODDS_API_REGIONS=uk,eu" in text
    assert "THE_ODDS_API_MARKETS=h2h,spreads,totals" in text
    assert "TELEGRAM_ALERT_SIGNALS=STRONG_BUY,BUY,WATCH" in text
    assert "TELEGRAM_ALERT_INTERVAL_MINUTES=5" in text
    assert "TELEGRAM_ALERT_RETENTION_DAYS=7" in text
    assert "TELEGRAM_ALERT_ARCHIVE_PATH=reports/telegram_alerts.json" in text
    assert "RECOMMENDATION_GATE_ENABLED=true" in text
    assert "RECOMMENDATION_ALLOWED_SIGNALS=STRONG_BUY,BUY" in text
    assert "RECOMMENDATION_REQUIRE_FRESH_ODDS=true" in text
    assert "RECOMMENDATION_MAX_ODDS_AGE_MINUTES=120" in text
    assert "RECOMMENDATION_MIN_BOOKMAKERS=1" in text
    assert "RECOMMENDATION_REQUIRE_SHARP_ANCHOR=false" in text
    assert "RECOMMENDATION_MIN_MARKET_EDGE=0.04" in text
    assert "MODEL_OPTIMIZER_ENABLED=true" in text
    assert "MODEL_OPTIMIZER_MANUAL_MIN_SAMPLES=20" in text
    assert "MODEL_OPTIMIZER_AUTO_APPLY_ENABLED=true" in text
    assert "MODEL_OPTIMIZER_AUTO_APPLY_MIN_SAMPLES=100" in text


def test_docker_compose_allows_free_provider_leagues_env_override() -> None:
    text = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "DATA_PROVIDER: ${DATA_PROVIDER:-free}" in text
    assert "FOOTBALL_DATA_SOURCE: ${FOOTBALL_DATA_SOURCE:-free}" in text
    assert "FOOTBALL_DATA_SEASON: ${FOOTBALL_DATA_SEASON:-2026}" in text
    assert "FREE_PROVIDER_SOURCES: ${FREE_PROVIDER_SOURCES:-espn,thesportsdb}" in text
    assert "FREE_PROVIDER_THESPORTSDB_BASE_URL: ${FREE_PROVIDER_THESPORTSDB_BASE_URL:-https://www.thesportsdb.com/api/v1/json/3}" in text
    assert "FREE_PROVIDER_FOOTBALL_LEAGUES: ${FREE_PROVIDER_FOOTBALL_LEAGUES:-" in text
    assert "ODDS_AGGREGATOR_ENABLED: ${ODDS_AGGREGATOR_ENABLED:-false}" in text
    assert "ODDS_AGGREGATOR_PROVIDER: ${ODDS_AGGREGATOR_PROVIDER:-the_odds_api}" in text
    assert "THE_ODDS_API_KEY: ${THE_ODDS_API_KEY:-}" in text
    assert "THE_ODDS_API_REGIONS: ${THE_ODDS_API_REGIONS:-uk,eu}" in text
    assert "THE_ODDS_API_MARKETS: ${THE_ODDS_API_MARKETS:-h2h,spreads,totals}" in text
    for league_id in [
        "kor.1",
        "kor.2",
        "jpn.1",
        "jpn.2",
        "aus.1",
        "bra.2",
        "arg.2",
        "usa.1",
        "usa.usl.1",
        "mex.2",
        "uefa.nations",
        "fifa.friendly",
        "club.friendly",
        "aff.championship",
        "caf.w.nations",
        "ecu.1",
        "bol.1",
    ]:
        assert league_id in text


def test_logging_redacts_telegram_bot_token() -> None:
    import logging

    record = logging.LogRecord(
        name="httpx",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="POST %s",
        args=("https://api.telegram.org/bot123456:ABC_def-GHI/sendMessage",),
        exc_info=None,
    )
    assert SensitiveDataFilter().filter(record) is True
    assert record.getMessage() == "POST https://api.telegram.org/bot<redacted>/sendMessage"


def test_logging_redacts_telegram_bot_token_from_url_objects() -> None:
    import logging

    class UrlLike:
        def __str__(self) -> str:
            return "https://api.telegram.org/bot123456:ABC_def-GHI/sendMessage"

    record = logging.LogRecord(
        name="httpx",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="HTTP Request: %s %s",
        args=("POST", UrlLike()),
        exc_info=None,
    )
    assert SensitiveDataFilter().filter(record) is True
    assert record.getMessage() == "HTTP Request: POST https://api.telegram.org/bot<redacted>/sendMessage"


def test_logging_file_handler_is_size_bounded() -> None:
    text = Path("config/logging.py").read_text(encoding="utf-8")
    assert "RotatingFileHandler" in text
    assert LOG_FILE_MAX_BYTES == 10 * 1024 * 1024
    assert LOG_FILE_BACKUP_COUNT == 5


def test_prediction_pipeline_runs_with_mock(mock_pipeline) -> None:
    results = mock_pipeline.run_today()
    assert len(results) == 1
    result = results[0]
    assert 0 <= result.hunter_score.score <= 100
    assert result.signal.signal.value in {"STRONG_BUY", "BUY", "WATCH", "PASS", "BLOCK"}
    assert result.market_prediction.score.text
    assert result.market_prediction.total_goals.pick in {"OVER", "UNDER", "NO_PLAY"}
    assert result.market_prediction.handicap.pick in {"HOME_HANDICAP", "AWAY_HANDICAP", "NO_PLAY"}
    assert result.market_prediction.total_goals.market_available is True
    assert result.market_prediction.handicap.market_available is True
    assert result.to_dict()["market_prediction"]["score"]["text"] == result.market_prediction.score.text


def test_prediction_pipeline_only_runs_today_upcoming_or_live_candidates() -> None:
    now = datetime(2026, 8, 5, 4, 0, tzinfo=timezone.utc)
    league = League(id="league", name="League", provider="mock")
    home = Team(id="home", name="Home", provider="mock")
    away = Team(id="away", name="Away", provider="mock")

    def fixture(fixture_id: str, start_time: datetime, status: FixtureStatus) -> Fixture:
        return Fixture(
            id=fixture_id,
            league=league,
            home_team=home,
            away_team=away,
            start_time=start_time,
            status=status,
            provider="mock",
        )

    class FakeDataHub:
        def get_today_fixtures(self) -> list[Fixture]:
            return [
                fixture("today-upcoming", now + timedelta(minutes=30), FixtureStatus.SCHEDULED),
                fixture("tomorrow", now + timedelta(days=1), FixtureStatus.SCHEDULED),
                fixture("already-started", now - timedelta(minutes=5), FixtureStatus.SCHEDULED),
                fixture("finished", now + timedelta(minutes=15), FixtureStatus.FINISHED),
            ]

        def get_live_matches(self) -> list[Fixture]:
            return [
                fixture("live-recent", now - timedelta(minutes=45), FixtureStatus.LIVE),
                fixture("live-stale", now - timedelta(hours=4), FixtureStatus.LIVE),
            ]

    pipeline = PredictionPipeline(SimpleNamespace(datahub=FakeDataHub()))
    called: list[str] = []

    def fake_run_fixture(fixture_id: str) -> str:
        called.append(fixture_id)
        return fixture_id

    pipeline.run_fixture = fake_run_fixture

    assert pipeline.run_today(now=now) == ["today-upcoming", "live-recent"]
    assert called == ["today-upcoming", "live-recent"]


def test_data_sync_commits_successful_fixtures_and_rolls_back_failed_one(monkeypatch) -> None:
    calls: list[str] = []
    fixtures = [
        SimpleNamespace(id="ok-1"),
        SimpleNamespace(id="bad"),
        SimpleNamespace(id="ok-2"),
    ]

    class FakeDataHub:
        provider = SimpleNamespace(name="fake-provider")

        def get_today_fixtures(self) -> list[SimpleNamespace]:
            return fixtures

    class FakeSession:
        current_fixture_id: str | None = None

        def __enter__(self) -> "FakeSession":
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def flush(self) -> None:
            calls.append(f"flush:{self.current_fixture_id}")
            if self.current_fixture_id == "bad":
                raise RuntimeError("simulated fixture write failure")

        def commit(self) -> None:
            calls.append("commit")

        def rollback(self) -> None:
            calls.append("rollback")

    class FakeRepository:
        def __init__(self, session: FakeSession) -> None:
            self.session = session

        def upsert_fixture(self, fixture: SimpleNamespace) -> SimpleNamespace:
            self.session.current_fixture_id = fixture.id
            calls.append(f"upsert:{fixture.id}")
            return SimpleNamespace(id=fixture.id)

        def add_sync_log(self, **kwargs) -> None:
            calls.append(f"sync-log:{kwargs['status']}")

    monkeypatch.setattr(data_sync_engine, "SessionLocal", FakeSession)
    monkeypatch.setattr(data_sync_engine, "SportsRepository", FakeRepository)

    summary = data_sync_engine.DataSync(FakeDataHub()).sync_today()

    assert summary.synced_count == 2
    assert summary.failed_count == 1
    assert summary.status == "partial"
    assert calls == [
        "upsert:ok-1",
        "flush:ok-1",
        "commit",
        "upsert:bad",
        "flush:bad",
        "rollback",
        "upsert:ok-2",
        "flush:ok-2",
        "commit",
        "sync-log:partial",
        "commit",
    ]


def test_prediction_archive_persists_prediction_result(mock_pipeline) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    result = mock_pipeline.run_today()[0]

    prediction_id = PredictionArchive(session_factory=Session).save(result)

    with Session() as session:
        prediction = session.get(Prediction, prediction_id)
        assert prediction is not None
        assert prediction.signal == result.signal.signal.value
        assert prediction.predicted_side == result.predicted_side
        assert prediction.breakdown_json["market_prediction"]["score"]["text"] == result.market_prediction.score.text


def test_prediction_archive_reuses_unchanged_snapshot(mock_pipeline) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    result = mock_pipeline.run_today()[0]
    result.fixture.start_time = _future_beijing_today_start()
    result.fixture.status = FixtureStatus.SCHEDULED
    archive = PredictionArchive(session_factory=Session)

    first = archive.save_if_changed(result)
    second = archive.save_if_changed(result)

    with Session() as session:
        assert session.query(Prediction).count() == 1

    assert first.created is True
    assert first.prediction_id is not None
    assert second.created is False
    assert second.skipped is True
    assert second.prediction_id == first.prediction_id


def test_feature_builder_missing_data_stays_neutral() -> None:
    fixture = Fixture(
        id="neutral-fixture",
        league=League(id="eng.1", name="Premier League"),
        home_team=Team(id="home", name="Home"),
        away_team=Team(id="away", name="Away"),
        start_time=datetime.now(timezone.utc),
    )

    class MissingDataHub:
        def get_fixture(self, fixture_id: str) -> Fixture:
            assert fixture_id == fixture.id
            return fixture

        def get_odds(self, fixture_id: str) -> list:
            raise RuntimeError("odds missing")

        def get_statistics(self, fixture_id: str):
            raise RuntimeError("stats missing")

    vector = FeatureBuilder(MissingDataHub()).build(fixture.id)

    assert vector.features["home_recent_form"] == 50.0
    assert vector.features["away_recent_form"] == 50.0
    assert vector.features["home_attack_index"] == 50.0
    assert vector.features["away_attack_index"] == 50.0
    assert vector.features["elo_difference"] == 50.0
    assert vector.features["market_heat"] == 50.0
    assert vector.features["home_advantage"] == 56.0
    assert "odds_unavailable" in vector.warnings
    assert "statistics_unavailable" in vector.warnings
    assert "standings_unavailable" in vector.warnings
    assert HunterRatingEngine().score(vector).confidence <= 0.55


def test_feature_builder_uses_standings_when_statistics_are_missing() -> None:
    fixture = Fixture(
        id="standings-fixture",
        league=League(id="eng.1", name="Premier League"),
        home_team=Team(id="home", name="Home"),
        away_team=Team(id="away", name="Away"),
        start_time=datetime.now(timezone.utc),
    )

    class StandingsDataHub:
        def get_fixture(self, fixture_id: str) -> Fixture:
            assert fixture_id == fixture.id
            return fixture

        def get_odds(self, fixture_id: str) -> list:
            assert fixture_id == fixture.id
            return []

        def get_statistics(self, fixture_id: str):
            assert fixture_id == fixture.id
            raise RuntimeError("stats missing")

        def get_standings(self, league_id: str) -> list[Standing]:
            assert league_id == fixture.league.id
            return [
                Standing(
                    league_id=league_id,
                    team=fixture.home_team,
                    rank=1,
                    points=42,
                    played=18,
                    wins=13,
                    draws=3,
                    losses=2,
                ),
                Standing(
                    league_id=league_id,
                    team=fixture.away_team,
                    rank=18,
                    points=12,
                    played=18,
                    wins=3,
                    draws=3,
                    losses=12,
                ),
            ]

    vector = FeatureBuilder(StandingsDataHub()).build(fixture.id)

    assert vector.features["home_recent_form"] > vector.features["away_recent_form"]
    assert vector.features["home_attack_index"] > vector.features["away_attack_index"]
    assert vector.features["home_defense_index"] > vector.features["away_defense_index"]
    assert vector.features["elo_difference"] > 50
    assert "statistics_unavailable" in vector.warnings
    assert "standings_unavailable" not in vector.warnings


def test_market_prediction_scoreline_varies_with_match_profile() -> None:
    model = MarketPredictionModel()
    fixture = Fixture(
        id="market-test",
        league=League(id="league", name="Debug League"),
        home_team=Team(id="home", name="Home"),
        away_team=Team(id="away", name="Away"),
        start_time=datetime.now(timezone.utc),
    )
    base = {name: 50.0 for name in [
        "home_recent_form",
        "away_recent_form",
        "home_attack_index",
        "away_attack_index",
        "home_defense_index",
        "away_defense_index",
        "elo_difference",
        "odds_move",
        "market_heat",
        "fatigue_index",
        "home_advantage",
        "injury_index",
        "live_momentum",
        "league_strength",
    ]}

    def score(overrides: dict[str, float]) -> tuple[str, str, str | None]:
        prediction = model.predict(fixture, FeatureVector("market-test", base | overrides), [])
        return prediction.score.text, prediction.moneyline_pick, prediction.predicted_side

    neutral = score({})
    home_strong = score({"home_attack_index": 70, "away_attack_index": 40, "elo_difference": 65, "home_advantage": 65})
    away_strong = score({"home_attack_index": 40, "away_attack_index": 70, "elo_difference": 35, "home_advantage": 45})
    low_total = score({"home_attack_index": 35, "away_attack_index": 35, "home_defense_index": 70, "away_defense_index": 70})
    high_total = score({"home_attack_index": 78, "away_attack_index": 76, "home_defense_index": 35, "away_defense_index": 35})

    assert neutral[1] == "DRAW"
    assert home_strong[1:] == ("HOME", "Home")
    assert away_strong[1:] == ("AWAY", "Away")
    assert len({neutral[0], home_strong[0], away_strong[0], low_total[0], high_total[0]}) >= 4
    assert not all(item == "2-1" for item in [neutral[0], home_strong[0], away_strong[0], low_total[0], high_total[0]])


def test_market_prediction_scoreline_uses_market_lines_when_features_are_sparse() -> None:
    model = MarketPredictionModel()
    fixture = Fixture(
        id="market-lines-score",
        league=League(id="league", name="Debug League"),
        home_team=Team(id="home", name="Home"),
        away_team=Team(id="away", name="Away"),
        start_time=datetime.now(timezone.utc),
    )
    sparse_features = {name: 50.0 for name in [
        "home_recent_form",
        "away_recent_form",
        "home_attack_index",
        "away_attack_index",
        "home_defense_index",
        "away_defense_index",
        "elo_difference",
        "odds_move",
        "market_heat",
        "fatigue_index",
        "home_advantage",
        "injury_index",
        "live_momentum",
        "league_strength",
    ]}
    vector = FeatureVector(
        fixture.id,
        sparse_features,
        warnings=["statistics_unavailable", "standings_unavailable"],
    )
    low_total_away_odds = [
        Odds(
            fixture_id=fixture.id,
            market=OddsMarket.TOTALS,
            bookmaker="DebugBook",
            line=2.0,
            over=2.20,
            under=1.72,
        ),
        Odds(
            fixture_id=fixture.id,
            market=OddsMarket.ASIAN_HANDICAP,
            bookmaker="DebugBook",
            line=0.5,
            home=1.95,
            away=1.85,
        ),
    ]
    high_total_home_odds = [
        Odds(
            fixture_id=fixture.id,
            market=OddsMarket.TOTALS,
            bookmaker="DebugBook",
            line=3.0,
            over=1.75,
            under=2.10,
        ),
        Odds(
            fixture_id=fixture.id,
            market=OddsMarket.ASIAN_HANDICAP,
            bookmaker="DebugBook",
            line=-0.75,
            home=1.80,
            away=2.05,
        ),
    ]

    low_total = model.predict(fixture, vector, low_total_away_odds)
    high_total = model.predict(fixture, vector, high_total_home_odds)

    assert low_total.score.text != high_total.score.text
    assert low_total.score.expected_home_goals < high_total.score.expected_home_goals
    assert low_total.score.expected_away_goals >= high_total.score.expected_away_goals


def test_live_score_prediction_respects_current_score_floor() -> None:
    model = MarketPredictionModel()
    fixture = Fixture(
        id="live-score-floor",
        league=League(id="league", name="Debug League"),
        home_team=Team(id="home", name="Home"),
        away_team=Team(id="away", name="Away"),
        start_time=datetime.now(timezone.utc) - timedelta(minutes=67),
        status=FixtureStatus.LIVE,
        score=Score(home=2, away=1, period="67", clock="67"),
    )
    features = {name: 50.0 for name in [
        "home_recent_form",
        "away_recent_form",
        "home_attack_index",
        "away_attack_index",
        "home_defense_index",
        "away_defense_index",
        "elo_difference",
        "odds_move",
        "market_heat",
        "fatigue_index",
        "home_advantage",
        "injury_index",
        "live_momentum",
        "league_strength",
    ]}

    prediction = model.predict(fixture, FeatureVector(fixture.id, features), [])

    assert prediction.score.home >= 2
    assert prediction.score.away >= 1
    assert all(
        int(text.split("-")[0]) >= 2 and int(text.split("-")[1]) >= 1
        for text in prediction.score.text.split(" / ")
    )


def test_historical_probability_model_uses_settled_results() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    league = League(id="league", name="Debug League", provider="mock")
    home = Team(id="home", name="Home", provider="mock")
    away = Team(id="away", name="Away", provider="mock")
    scores = [(3, 1), (2, 0), (2, 1), (3, 2), (1, 0), (2, 1)]

    with Session() as session:
        repo = SportsRepository(session)
        for index, (home_score, away_score) in enumerate(scores, start=1):
            historical_fixture = Fixture(
                id=f"history-{index}",
                league=league,
                home_team=home,
                away_team=away,
                start_time=now - timedelta(days=index * 7),
                status=FixtureStatus.FINISHED,
                provider="mock",
            )
            db_fixture = repo.upsert_fixture(historical_fixture)
            repo.upsert_match_result(db_fixture, home_score=home_score, away_score=away_score)
        session.commit()

    upcoming = Fixture(
        id="future",
        league=league,
        home_team=home,
        away_team=away,
        start_time=now,
        status=FixtureStatus.SCHEDULED,
        provider="mock",
    )
    projection = HistoricalProbabilityModel(
        session_factory=Session,
        min_league_matches=4,
    ).predict(upcoming)

    assert projection is not None
    assert projection.source == "historical_league_poisson"
    assert projection.sample_count == len(scores)
    assert projection.home_team_sample_count == len(scores)
    assert projection.away_team_sample_count == len(scores)
    assert projection.expected_home_goals > projection.expected_away_goals
    assert projection.outcomes.home > projection.outcomes.away
    assert projection.total_goals_probability(2.25, "OVER").win > 0
    assert projection.handicap_probability("home", -0.25).effective > 0.5


def test_historical_probability_model_skips_irrelevant_global_only_history() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    other_league = League(id="other-league", name="Other League", provider="mock")
    other_home = Team(id="other-home", name="Other Home", provider="mock")
    other_away = Team(id="other-away", name="Other Away", provider="mock")

    with Session() as session:
        repo = SportsRepository(session)
        for index in range(1, 7):
            historical_fixture = Fixture(
                id=f"other-history-{index}",
                league=other_league,
                home_team=other_home,
                away_team=other_away,
                start_time=now - timedelta(days=index * 5),
                status=FixtureStatus.FINISHED,
                provider="mock",
            )
            db_fixture = repo.upsert_fixture(historical_fixture)
            repo.upsert_match_result(db_fixture, home_score=1, away_score=1)
        session.commit()

    upcoming = Fixture(
        id="unrelated-future",
        league=League(id="new-league", name="New League", provider="mock"),
        home_team=Team(id="new-home", name="New Home", provider="mock"),
        away_team=Team(id="new-away", name="New Away", provider="mock"),
        start_time=now,
        status=FixtureStatus.SCHEDULED,
        provider="mock",
    )

    projection = HistoricalProbabilityModel(
        session_factory=Session,
        min_league_matches=4,
    ).predict(upcoming)

    assert projection is None


def test_market_prediction_uses_probability_projection_for_edges_and_ev() -> None:
    fixture = Fixture(
        id="probability-market",
        league=League(id="league", name="Debug League", provider="mock"),
        home_team=Team(id="home", name="Home", provider="mock"),
        away_team=Team(id="away", name="Away", provider="mock"),
        start_time=datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc),
        provider="mock",
    )
    projection = ProbabilityProjection(
        source="historical_league_poisson",
        sample_count=20,
        league_sample_count=20,
        home_team_sample_count=8,
        away_team_sample_count=8,
        expected_home_goals=0.9,
        expected_away_goals=1.7,
        outcomes=OutcomeProbabilities(home=0.20, draw=0.14, away=0.66),
        scores=[
            ScoreProbability(home=0, away=1, probability=0.34),
            ScoreProbability(home=1, away=2, probability=0.20),
            ScoreProbability(home=0, away=2, probability=0.12),
            ScoreProbability(home=1, away=1, probability=0.14),
            ScoreProbability(home=1, away=0, probability=0.10),
            ScoreProbability(home=2, away=1, probability=0.10),
        ],
    )

    class FakeProbabilityModel:
        def predict(self, requested_fixture: Fixture) -> ProbabilityProjection:
            assert requested_fixture is fixture
            return projection

    neutral_features = {name: 50.0 for name in [
        "home_recent_form",
        "away_recent_form",
        "home_attack_index",
        "away_attack_index",
        "home_defense_index",
        "away_defense_index",
        "elo_difference",
        "odds_move",
        "market_heat",
        "fatigue_index",
        "home_advantage",
        "injury_index",
        "live_momentum",
        "league_strength",
    ]}
    odds = [
        Odds(
            fixture_id=fixture.id,
            market=OddsMarket.TOTALS,
            bookmaker="DebugBook",
            line=2.5,
            over=1.90,
            under=1.95,
            provider="mock",
        ),
        Odds(
            fixture_id=fixture.id,
            market=OddsMarket.ASIAN_HANDICAP,
            bookmaker="DebugBook",
            line=0.25,
            home=1.91,
            away=1.91,
            provider="mock",
        ),
    ]

    prediction = MarketPredictionModel(probability_model=FakeProbabilityModel()).predict(
        fixture,
        FeatureVector(fixture.id, neutral_features),
        odds,
    )

    assert prediction.model_source == "historical_league_poisson"
    assert prediction.sample_count == 20
    assert prediction.probabilities == {"home": 0.2, "draw": 0.14, "away": 0.66}
    assert prediction.moneyline_pick == "AWAY"
    assert prediction.predicted_side == "Away"
    assert prediction.score.text.startswith("0-1")
    assert prediction.total_goals.pick == "UNDER"
    assert prediction.total_goals.model_probability == 0.7
    assert prediction.total_goals.market_probability is not None
    assert prediction.total_goals.expected_value is not None
    assert prediction.handicap.pick == "AWAY_HANDICAP"
    assert prediction.handicap.model_probability == 0.695
    assert prediction.handicap.market_probability is not None
    assert prediction.handicap.expected_value is not None


def test_today_recommendations_archive_prediction_results(mock_pipeline) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)

    payload = build_today_recommendations(
        mock_pipeline,
        include_pass=True,
        prediction_archive=PredictionArchive(session_factory=Session),
    )

    with Session() as session:
        assert session.query(Prediction).count() == len(mock_pipeline.run_today())
        assert session.query(OddsSnapshot).count() >= 1

    assert payload["archive"]["created_count"] == len(mock_pipeline.run_today())
    assert payload["archive"]["items"][0]["odds_snapshot_count"] >= 1
    assert payload["items"][0]["prediction_id"] is not None
    assert payload["items"][0]["score_prediction"]
    assert payload["items"][0]["total_goals"]
    assert payload["items"][0]["handicap"]


def test_archived_recommendations_read_from_prediction_archive(mock_pipeline) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    result = mock_pipeline.run_today()[0]
    result.fixture.start_time = _future_beijing_today_start()
    result.fixture.status = FixtureStatus.SCHEDULED
    PredictionArchive(session_factory=Session).save_if_changed(result)

    payload = build_archived_recommendations(include_pass=True, session_factory=Session)

    assert payload["source"] == "predictions_archive"
    assert payload["count"] == 1
    assert payload["items"][0]["prediction_id"] is not None
    assert payload["items"][0]["match"].count("对阵") == 1
    assert payload["items"][0]["score_prediction"]["text"] == result.market_prediction.score.text






def test_archived_recommendations_skip_settled_fixtures(mock_pipeline) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    result = mock_pipeline.run_today()[0]
    PredictionArchive(session_factory=Session).save_if_changed(result)

    with Session() as session:
        prediction = session.scalar(select(Prediction))
        assert prediction is not None
        fixture = prediction.fixture
        fixture.status = FixtureStatus.FINISHED.value
        SportsRepository(session).upsert_match_result(fixture, home_score=2, away_score=1)
        session.commit()

    payload = build_archived_recommendations(include_pass=True, session_factory=Session)

    assert payload["count"] == 0
    assert payload["items"] == []


def test_dashboard_latest_predictions_skip_previous_beijing_day_predictions(mock_pipeline) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    result = mock_pipeline.run_today()[0]
    PredictionArchive(session_factory=Session).save_if_changed(result)

    with Session() as session:
        prediction = session.scalar(select(Prediction))
        assert prediction is not None
        prediction.created_at = datetime.now(timezone.utc) - timedelta(days=1)
        session.commit()

    with Session() as session:
        items = DashboardRepository(session).latest_predictions()

    assert items == []


def test_dashboard_latest_predictions_skip_stale_live_fixtures(mock_pipeline) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    result = mock_pipeline.run_today()[0]
    PredictionArchive(session_factory=Session).save_if_changed(result)

    with Session() as session:
        prediction = session.scalar(select(Prediction))
        assert prediction is not None
        fixture = prediction.fixture
        fixture.status = FixtureStatus.LIVE.value
        fixture.start_time = datetime.now(timezone.utc) - timedelta(hours=5)
        session.commit()

    with Session() as session:
        items = DashboardRepository(session).latest_predictions()

    assert items == []


def test_dashboard_latest_predictions_skip_stale_started_fixtures(mock_pipeline) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    result = mock_pipeline.run_today()[0]
    PredictionArchive(session_factory=Session).save_if_changed(result)

    with Session() as session:
        prediction = session.scalar(select(Prediction))
        assert prediction is not None
        fixture = prediction.fixture
        fixture.status = FixtureStatus.SCHEDULED.value
        fixture.start_time = datetime.now(timezone.utc) - timedelta(hours=3)
        session.commit()

    with Session() as session:
        items = DashboardRepository(session).latest_predictions()

    assert items == []


def test_dashboard_latest_predictions_skip_fixtures_after_beijing_today(mock_pipeline) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    result = mock_pipeline.run_today()[0]
    PredictionArchive(session_factory=Session).save_if_changed(result)

    with Session() as session:
        prediction = session.scalar(select(Prediction))
        assert prediction is not None
        fixture = prediction.fixture
        fixture.status = FixtureStatus.SCHEDULED.value
        fixture.start_time = _tomorrow_beijing_start()
        session.commit()

    with Session() as session:
        items = DashboardRepository(session).latest_predictions()

    assert items == []


def test_archived_recommendations_show_latest_fixture_once(mock_pipeline) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    result = mock_pipeline.run_today()[0]
    result.fixture.start_time = _future_beijing_today_start()
    result.fixture.status = FixtureStatus.SCHEDULED
    archive = PredictionArchive(session_factory=Session)
    first_id = archive.save(result)
    second_id = archive.save(result)

    payload = build_archived_recommendations(include_pass=True, session_factory=Session)

    assert first_id != second_id
    assert payload["count"] == 1
    assert payload["items"][0]["prediction_id"] == second_id


def test_dashboard_latest_predictions_show_fixture_once(mock_pipeline) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    result = mock_pipeline.run_today()[0]
    result.fixture.start_time = _future_beijing_today_start()
    result.fixture.status = FixtureStatus.SCHEDULED
    archive = PredictionArchive(session_factory=Session)
    archive.save(result)
    latest_id = archive.save(result)

    with Session() as session:
        items = DashboardRepository(session).latest_predictions()

    assert [item["id"] for item in items].count(latest_id) == 1
    assert len([item for item in items if item["fixture"] == items[0]["fixture"]]) == 1

def test_recommendations_export_csv_contains_prediction_fields(mock_pipeline) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    result = mock_pipeline.run_today()[0]
    result.fixture.start_time = _future_beijing_today_start()
    result.fixture.status = FixtureStatus.SCHEDULED
    PredictionArchive(session_factory=Session).save_if_changed(result)

    csv_body = build_recommendations_export_csv(include_pass=True, session_factory=Session)
    rows = list(csv.DictReader(StringIO(csv_body.lstrip("\ufeff"))))

    assert rows
    assert rows[0]["\u8054\u8d5b"]
    assert "\u5bf9\u9635" in rows[0]["\u6bd4\u8d5b"]
    assert rows[0]["\u4fe1\u53f7"] in {"\u5f3a\u70c8\u63a8\u8350", "\u63a8\u8350", "\u89c2\u5bdf", "\u8df3\u8fc7", "\u98ce\u63a7\u62e6\u622a"}
    assert rows[0]["\u6bd4\u5206\u9884\u6d4b"] == result.market_prediction.score.text
    assert rows[0]["\u5927\u5c0f\u7403"] == result.market_prediction.total_goals.label
    assert rows[0]["\u8ba9\u7403"] == result.market_prediction.handicap.label


def test_recommendations_export_csv_endpoint(monkeypatch) -> None:
    def fake_export(include_pass: bool = False, limit: int = 200) -> str:
        assert include_pass is True
        assert limit == 3
        return "\ufeff\u8054\u8d5b,\u6bd4\u8d5b\n\u5df4\u897f\u4e59\u7ea7\u8054\u8d5b,A \u5bf9\u9635 B\n"

    monkeypatch.setattr(recommendations_router, "build_recommendations_export_csv", fake_export)
    response = TestClient(app).get("/api/recommendations/export.csv?include_pass=true&limit=3")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert "\u8054\u8d5b,\u6bd4\u8d5b" in response.text

def test_evaluation_metrics_show_no_risk_sample_as_empty() -> None:
    metrics = calculate_metrics([
        {
            "actionable": True,
            "won": True,
            "stake": 1,
            "profit": 1,
            "confidence": 0.8,
            "risk_level": "LOW",
            "market_results": {},
        }
    ])
    report = EvaluationReport(period="daily", report_date=datetime.now(timezone.utc).date(), metrics=metrics, settled_count=1)

    assert metrics.risk_effectiveness is None
    assert "暂无高风险/拦截样本" in report.to_markdown()


def test_settlement_and_evaluation_loop_records_learning(mock_pipeline, tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    result = mock_pipeline.run_today()[0]
    PredictionArchive(session_factory=Session).save(result)
    result.fixture.status = FixtureStatus.FINISHED
    result.fixture.score = Score(home=3, away=1)

    settlement = SettlementService(session_factory=Session).settle_fixtures([result.fixture])
    report = EvaluationRunner(
        dataset=EvaluationDataset(session_factory=Session),
        reports_dir=tmp_path,
    ).daily()

    with Session() as session:
        assert session.query(MatchResult).count() == 1
        assert session.query(LearningRecord).count() == 1

    assert settlement.settled_count == 1
    assert report.settled_count == 1
    assert report.learning_records_created == 1
    assert report.metrics.signal_hit_rate == 1.0
    assert report.metrics.by_market["moneyline"] == 1.0
    assert report.metrics.by_market["totals"] == 1.0
    assert report.metrics.by_market["handicap"] == 1.0
    assert report.wins
    assert report.losses == ["本周期暂无未命中推荐。"]
    markdown = report.to_markdown()
    assert " vs " not in markdown
    assert "WATCH" not in markdown
    assert "BUY" not in markdown
    assert "# SportsHunter-AI 每日复盘" in report.to_markdown()
    assert "## 核心结论" in report.to_markdown()
    assert "## 命中原因" in report.to_markdown()
    assert "## 未命中原因" in report.to_markdown()
    assert "## 信心校准" in report.to_markdown()
    assert "## 模块贡献" in report.to_markdown()
    assert report.overview
    assert report.confidence_notes
    assert (tmp_path / "daily_report.md").exists()

    period_report = EvaluationRunner(
        dataset=EvaluationDataset(session_factory=Session),
        reports_dir=tmp_path,
    ).run_for_days(7)
    assert period_report.period == "last_7_days"
    assert period_report.settled_count == 1
    assert period_report.learning_records_created == 0
    assert "# SportsHunter-AI \u8fd17\u5929" in period_report.to_markdown()
    assert (tmp_path / "last_7_days_report.md").exists()


def test_evaluation_dataset_uses_latest_prediction_per_fixture(mock_pipeline) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    result = mock_pipeline.run_today()[0]

    first_id = PredictionArchive(session_factory=Session).save(result)
    second_id = PredictionArchive(session_factory=Session).save(result)

    with Session() as session:
        first = session.get(Prediction, first_id)
        second = session.get(Prediction, second_id)
        assert first is not None
        assert second is not None
        first.created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        second.created_at = datetime.now(timezone.utc)
        session.commit()

    result.fixture.status = FixtureStatus.FINISHED
    result.fixture.score = Score(home=3, away=1)
    SettlementService(session_factory=Session).settle_fixtures([result.fixture])

    rows = EvaluationDataset(session_factory=Session).rows("daily")

    assert len(rows) == 1
    assert rows[0]["prediction_id"] == second_id

    with Session() as session:
        saved_result = session.scalar(select(MatchResult))
        assert saved_result is not None
        saved_result.settled_at = datetime.now(timezone.utc) - timedelta(days=5)
        session.commit()

    assert EvaluationDataset(session_factory=Session).rows_for_days(3) == []
    assert len(EvaluationDataset(session_factory=Session).rows_for_days(7)) == 1


def test_evaluation_dataset_summarizes_lightweight_odds_context(mock_pipeline) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    result = mock_pipeline.run_today()[0]
    result.odds = []
    prediction_id = PredictionArchive(session_factory=Session).save(result)
    result.fixture.status = FixtureStatus.FINISHED
    result.fixture.score = Score(home=2, away=1)
    SettlementService(session_factory=Session).settle_fixtures([result.fixture])

    with Session() as session:
        prediction = session.get(Prediction, prediction_id)
        assert prediction is not None
        market_prediction = dict((prediction.breakdown_json or {}).get("market_prediction") or {})
        market_prediction["moneyline_pick"] = ""
        market_prediction["total_goals"] = {
            "line": 2.5,
            "pick": "OVER",
            "label": "\u5927 2.5",
            "expected_total": 2.9,
            "confidence": 0.66,
            "reason": "test",
            "edge": 0.12,
            "bookmaker": "EarlyBook",
            "over_odds": 2.1,
            "under_odds": 1.7,
            "market_available": True,
            "expected_value": 0.08,
        }
        prediction.breakdown_json = {
            **(prediction.breakdown_json or {}),
            "market_prediction": market_prediction,
        }
        db_fixture = prediction.fixture
        kickoff = db_fixture.start_time
        if kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=timezone.utc)
        repo = SportsRepository(session)
        repo.add_odds_snapshot(
            db_fixture,
            Odds(
                fixture_id=result.fixture.id,
                market=OddsMarket.TOTALS,
                bookmaker="EarlyBook",
                captured_at=kickoff - timedelta(hours=3),
                line=2.5,
                over=1.91,
                under=1.91,
                provider="test",
                raw={"payload": "x" * 1000},
            ),
            stage="pre_match",
        )
        repo.add_odds_snapshot(
            db_fixture,
            Odds(
                fixture_id=result.fixture.id,
                market=OddsMarket.TOTALS,
                bookmaker="Pinnacle",
                captured_at=kickoff - timedelta(minutes=20),
                line=2.5,
                over=1.90,
                under=1.90,
                provider="test",
                raw={"payload": "z" * 1000},
            ),
            stage="closing",
        )
        repo.add_odds_snapshot(
            db_fixture,
            Odds(
                fixture_id=result.fixture.id,
                market=OddsMarket.EUROPEAN,
                bookmaker="ClosingBook",
                captured_at=kickoff - timedelta(minutes=10),
                home=1.9,
                draw=3.2,
                away=4.1,
                provider="test",
                raw={"payload": "y" * 1000},
            ),
            stage="closing",
        )
        session.commit()

    rows = EvaluationDataset(session_factory=Session).rows_for_days(3)

    assert len(rows) == 1
    assert rows[0]["odds_snapshot_count"] == 3
    assert rows[0]["has_closing_odds"] is True
    assert rows[0]["latest_odds_stage"] == "closing"
    assert rows[0]["odds_freshness_bucket"] == "0_30"
    assert rows[0]["odds_bookmaker_count"] == 3
    assert rows[0]["has_sharp_anchor"] is True
    assert rows[0]["clv"]["count"] == 1
    assert rows[0]["clv"]["trusted_count"] == 1
    assert abs(rows[0]["avg_clv"] - 0.1053) < 0.0001
    assert rows[0]["latest_odds_bookmaker"] == "ClosingBook"
    assert rows[0]["latest_odds_minutes_before_kickoff"] == 10
    assert rows[0]["odds_markets"] == ["european", "totals"]


def test_settlement_scans_pending_archived_predictions(mock_pipeline) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    result = mock_pipeline.run_today()[0]
    result.fixture.start_time = datetime.now(timezone.utc) - timedelta(hours=3)
    PredictionArchive(session_factory=Session).save_if_changed(result)

    finished_fixture = result.fixture
    finished_fixture.status = FixtureStatus.FINISHED
    finished_fixture.score = Score(home=3, away=1)

    class FakeDataHub:
        def get_fixture(self, fixture_id: str) -> Fixture:
            assert fixture_id == result.fixture.id
            return finished_fixture

    summary = SettlementService(session_factory=Session).settle_pending_predictions(FakeDataHub())

    with Session() as session:
        saved_result = session.scalar(select(MatchResult))

    assert summary.checked_count == 1
    assert summary.settled_count == 1
    assert saved_result is not None
    assert saved_result.home_score == 3
    assert saved_result.away_score == 1


def test_settlement_updates_unsettled_fixture_status_without_result(mock_pipeline) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    result = mock_pipeline.run_today()[0]
    PredictionArchive(session_factory=Session).save_if_changed(result)

    result.fixture.status = FixtureStatus.POSTPONED
    result.fixture.score = Score()
    summary = SettlementService(session_factory=Session).settle_fixtures([result.fixture])

    with Session() as session:
        fixture = session.execute(select(Prediction).limit(1)).scalar_one().fixture
        saved_result = session.scalar(select(MatchResult))

    assert summary.skipped_count == 1
    assert summary.settled_count == 0
    assert saved_result is None
    assert fixture.status == FixtureStatus.POSTPONED.value


def test_settlement_uses_contextual_provider_lookup_for_pending_predictions(mock_pipeline) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    result = mock_pipeline.run_today()[0]
    result.fixture.league.id = "bra.2"
    result.fixture.start_time = datetime.now(timezone.utc) - timedelta(hours=6)
    PredictionArchive(session_factory=Session).save_if_changed(result)

    finished_fixture = result.fixture
    finished_fixture.status = FixtureStatus.FINISHED
    finished_fixture.score = Score(home=2, away=0)

    class ContextProvider:
        def __init__(self) -> None:
            self.calls = []

        def get_fixture_by_context(self, fixture_id: str, league_id: str | None = None, kickoff=None) -> Fixture:
            self.calls.append((fixture_id, league_id, kickoff))
            return finished_fixture

    class FakeDataHub:
        def __init__(self) -> None:
            self.provider = ContextProvider()

        def get_fixture(self, fixture_id: str) -> Fixture:
            raise AssertionError("settlement should use provider context lookup when available")

    datahub = FakeDataHub()
    summary = SettlementService(session_factory=Session).settle_pending_predictions(datahub)

    with Session() as session:
        saved_result = session.scalar(select(MatchResult))

    assert summary.checked_count == 1
    assert summary.settled_count == 1
    assert saved_result is not None
    assert saved_result.home_score == 2
    assert saved_result.away_score == 0
    assert datahub.provider.calls[0][1] == "bra.2"
    assert datahub.provider.calls[0][2] is not None


def test_model_optimizer_suggests_and_applies_conservative_weights(mock_pipeline) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    result = mock_pipeline.run_today()[0]
    PredictionArchive(session_factory=Session).save(result)
    result.fixture.status = FixtureStatus.FINISHED
    result.fixture.score = Score(home=0, away=2)

    SettlementService(session_factory=Session).settle_fixtures([result.fixture])
    optimizer = ModelOptimizer(
        dataset=EvaluationDataset(session_factory=Session),
        session_factory=Session,
        min_recommended_sample=1,
    )
    report = optimizer.build_report()
    applied = optimizer.apply()

    assert report.can_apply is True
    assert report.suggestions
    assert applied["success"] is True
    assert applied["applied"] is True
    with Session() as session:
        model_version = session.scalar(select(ModelVersion).where(ModelVersion.name == "Hunter"))
        assert model_version is not None
        assert model_version.version.startswith("v1-opt-")
        active_weights = load_active_rating_weights(session)
    assert active_weights != report.current_weights
    assert round(sum(active_weights.values()), 2) == 100.0


def test_scheduled_model_optimizer_check_observes_before_manual_threshold(monkeypatch, tmp_path) -> None:
    settings = Settings(
        model_optimizer_status_path=tmp_path / "optimizer_status.json",
        model_optimizer_manual_min_samples=20,
        model_optimizer_auto_apply_enabled=False,
        _env_file=None,
    )

    class FakeReport:
        def to_dict(self) -> dict:
            return {
                "can_apply": True,
                "sample_count": 3,
                "suggestions": [{"module": "team_strength"}],
            }

    class FakeOptimizer:
        def __init__(self, min_recommended_sample: int) -> None:
            self.min_recommended_sample = min_recommended_sample

        def build_report(self, period: str) -> FakeReport:
            return FakeReport()

        def apply(self, period: str) -> dict:
            raise AssertionError("auto apply should not run before manual threshold")

    monkeypatch.setattr(optimizer_scheduler, "ModelOptimizer", FakeOptimizer)
    payload = optimizer_scheduler.run_scheduled_optimizer_check(settings)
    saved = json.loads(settings.model_optimizer_status_path.read_text(encoding="utf-8"))

    assert payload["action"] == "observe"
    assert payload["applied"] is None
    assert saved["action"] == "observe"
    assert saved["report"]["sample_count"] == 3


def test_scheduled_model_optimizer_check_uses_manual_review_at_threshold(monkeypatch, tmp_path) -> None:
    settings = Settings(
        model_optimizer_status_path=tmp_path / "optimizer_status.json",
        model_optimizer_manual_min_samples=20,
        model_optimizer_auto_apply_enabled=False,
        _env_file=None,
    )

    class FakeReport:
        def to_dict(self) -> dict:
            return {
                "can_apply": True,
                "sample_count": 20,
                "suggestions": [{"module": "team_strength"}],
            }

    class FakeOptimizer:
        def __init__(self, min_recommended_sample: int) -> None:
            self.min_recommended_sample = min_recommended_sample

        def build_report(self, period: str) -> FakeReport:
            return FakeReport()

        def apply(self, period: str) -> dict:
            raise AssertionError("auto apply is disabled")

    monkeypatch.setattr(optimizer_scheduler, "ModelOptimizer", FakeOptimizer)
    payload = optimizer_scheduler.run_scheduled_optimizer_check(settings)

    assert payload["action"] == "manual_review"
    assert payload["applied"] is None


def test_signal_strategy_balanced_alert_thresholds() -> None:
    assert SIGNAL_STRATEGY["buy"]["score"] == 82.0
    assert SIGNAL_STRATEGY["watch"]["score_min"] == 60.0
    assert SIGNAL_STRATEGY["watch"]["score_max"] == 82.0
    assert SIGNAL_STRATEGY["watch"]["stake"] == 0.25
    assert decide_signal(82.0, RiskLevel.LOW, 0.5) == Signal.BUY
    assert decide_signal(60.0, RiskLevel.LOW, 0.5) == Signal.WATCH
    assert decide_signal(59.9, RiskLevel.LOW, 0.5) == Signal.PASS


def test_repository_keeps_odds_history(mock_settings) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    provider = MockProvider(mock_settings)
    fixture = provider.get_fixture("history-001")
    odds = provider.get_odds(fixture.id)[0]
    with Session() as session:
        repo = SportsRepository(session)
        db_fixture = repo.upsert_fixture(fixture)
        session.flush()
        repo.add_odds_snapshot(db_fixture, odds)
        repo.add_odds_snapshot(db_fixture, odds)
        session.commit()
        snapshots = list(session.scalars(select(OddsSnapshot)))
    assert len(snapshots) == 2


def test_recommendation_gate_blocks_watch_and_weak_league() -> None:
    pipeline = _fake_recommendation_pipeline()
    buy, watch = pipeline.run_today()[:2]
    odds = pipeline.context.datahub.get_odds(buy.fixture.id)
    now = buy.fixture.start_time - timedelta(minutes=30)
    settings = Settings(data_provider="mock", _env_file=None)

    watch_decision = RecommendationGate(settings, history_rows=[]).evaluate(watch, odds=odds, now=now)
    assert watch_decision.passed is False
    assert "signal_not_actionable" in watch_decision.reasons

    weak_rows = [
        {"league": "Debug League", "actionable": True, "won": False, "stake": 1, "profit": -1}
        for _ in range(settings.recommendation_league_min_samples)
    ]
    weak_league_decision = RecommendationGate(settings, history_rows=weak_rows).evaluate(buy, odds=odds, now=now)
    assert weak_league_decision.passed is False
    assert "league_recent_performance_weak" in weak_league_decision.reasons


def test_recommendation_gate_blocks_missing_market_edge() -> None:
    pipeline = _fake_recommendation_pipeline()
    result = pipeline.run_today()[0]
    result.market_prediction.total_goals.pick = "NO_PLAY"
    result.market_prediction.total_goals.edge = 0.0
    result.market_prediction.handicap.pick = "NO_PLAY"
    result.market_prediction.handicap.edge = 0.0
    now = result.fixture.start_time - timedelta(minutes=30)

    decision = RecommendationGate(Settings(data_provider="mock", _env_file=None), history_rows=[]).evaluate(
        result,
        odds=pipeline.context.datahub.get_odds(result.fixture.id),
        now=now,
    )

    assert decision.passed is False
    assert "market_edge_too_small" in decision.reasons


def test_recommendation_gate_blocks_stale_odds() -> None:
    pipeline = _fake_recommendation_pipeline()
    result = pipeline.run_today()[0]
    now = result.fixture.start_time - timedelta(minutes=30)
    stale_odds = [
        Odds(
            fixture_id=result.fixture.id,
            market=OddsMarket.EUROPEAN,
            bookmaker="DebugBook",
            captured_at=now - timedelta(hours=3),
            home=1.80,
            draw=3.50,
            away=4.50,
            provider="mock",
        )
    ]
    settings = Settings(
        data_provider="mock",
        recommendation_max_odds_age_minutes=60,
        _env_file=None,
    )

    decision = RecommendationGate(settings, history_rows=[]).evaluate(result, odds=stale_odds, now=now)

    assert decision.passed is False
    assert "odds_stale" in decision.reasons
    assert decision.metrics["odds_quality"]["freshest_age_minutes"] == 180.0


def test_api_health() -> None:
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["app"] == "SportsHunter-AI"


def test_api_dependencies_reuse_datahub_cache() -> None:
    dependencies.get_datahub.cache_clear()
    try:
        first = dependencies.get_datahub()
        second = dependencies.get_datahub()
        pipeline = dependencies.get_prediction_pipeline()
        assert first is second
        assert pipeline.context.datahub is first
    finally:
        dependencies.get_datahub.cache_clear()


def test_dashboard_page_serves_operations_console() -> None:
    response = TestClient(app).get("/dashboard")
    assert response.status_code == 200
    assert "dashboard-root" in response.text
    assert "/dashboard/static/app.js" in response.text
    assert "recommendations-scroll" in response.text
    assert "recommendation-signal-filter" in response.text
    assert "recommendation-league-filter" in response.text
    assert "recommendation-time-filter" in response.text
    assert "recommendation-export-button" in response.text
    assert "beijingToday" in response.text
    assert "period-control" in response.text
    assert "model-performance-caption" in response.text
    assert "dashboard-summary-link" in response.text
    assert "odds-quality-performance" in response.text
    assert "clv-performance" in response.text
    assert "odds-freshness-performance" in response.text
    assert "20260810-odds-evidence" in response.text
    assert "&#26102;&#38388;" in response.text
    assert "体育预测运行看板" in response.text
    assert "检查数据源" in response.text
    assert "今日推荐归档" in response.text
    assert "模型表现" in response.text
    assert "模块偏差" in response.text
    assert "盘口表现" in response.text
    assert "模型优化建议" in response.text




def test_dashboard_latest_predictions_include_kickoff(mock_pipeline) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    result = mock_pipeline.run_today()[0]
    result.fixture.start_time = _future_beijing_today_start()
    result.fixture.status = FixtureStatus.SCHEDULED
    PredictionArchive(session_factory=Session).save_if_changed(result)

    with Session() as session:
        items = DashboardRepository(session).latest_predictions()

    assert items
    parsed_kickoff = datetime.fromisoformat(items[0]["kickoff"])
    assert parsed_kickoff.tzinfo is not None
    assert parsed_kickoff == result.fixture.start_time.astimezone(timezone.utc)

def test_dashboard_summary_returns_operational_payload(mock_settings) -> None:
    app.dependency_overrides[dashboard_get_datahub] = lambda: DataHub(MockProvider(mock_settings))
    try:
        response = TestClient(app).get("/api/dashboard/summary")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"]["provider"] == "mock"
    assert payload["provider"]["health"] in {"unknown", "ok"}
    assert payload["recommendations"]["source"] == "predictions_archive_unique_latest"
    assert "database" in payload
    assert "analytics" in payload
    assert "performance" in payload["analytics"]
    assert "odds_quality_performance" in payload["analytics"]["performance"]
    assert "clv_performance" in payload["analytics"]["performance"]
    assert "odds_freshness_performance" in payload["analytics"]["performance"]
    assert "signal_distribution" in payload["analytics"]
    assert "prediction_trend" in payload["analytics"]
    assert "model_optimizer" in payload
    assert "suggestions" in payload["model_optimizer"]
    assert "reports" in payload
    assert payload["period_days"] == 30
    assert payload["period_options"] == [3, 7, 15, 30]
    assert payload["analytics"]["period_days"] == 30
    assert payload["analytics"]["performance"]["period_days"] == 30
    assert payload["reports"]["period_days"] == 30

    app.dependency_overrides[dashboard_get_datahub] = lambda: DataHub(MockProvider(mock_settings))
    try:
        response = TestClient(app).get("/api/dashboard/summary?period_days=7")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["period_days"] == 7
    assert payload["analytics"]["period_days"] == 7
    assert payload["analytics"]["performance"]["period_days"] == 7
    assert payload["reports"]["period_days"] == 7


def test_dashboard_provider_status_does_not_deep_scan_provider() -> None:
    class SlowDataHub:
        provider = SimpleNamespace(name="slow-provider", last_health=None)

        def provider_status(self):
            raise AssertionError("summary should not deep-scan provider health")

    payload = dashboard_service._provider_status(SlowDataHub())

    assert payload["provider"] == "slow-provider"
    assert payload["health"] == "unknown"


def test_model_optimizer_api_returns_structured_payload() -> None:
    response = TestClient(app).get("/api/model/optimizer/suggestions")

    assert response.status_code == 200
    payload = response.json()
    assert "status" in payload
    assert "current_weights" in payload
    assert "suggested_weights" in payload
    assert "suggestions" in payload


def test_dashboard_data_quality_check_reports_odds_coverage(mock_settings) -> None:
    app.dependency_overrides[dashboard_get_datahub] = lambda: DataHub(MockProvider(mock_settings))
    try:
        response = TestClient(app).post("/api/dashboard/data-quality/check")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "mock"
    assert payload["fixtures_count"] == 1
    assert payload["fixtures_with_odds"] == 1
    assert payload["odds_market_counts"] == {"european": 1, "asian_handicap": 1, "totals": 1}
    assert payload["odds_coverage"]["european"]["ratio"] == 1.0
    assert payload["sample_fixtures"][0]["odds_markets"] == ["asian_handicap", "european", "totals"]
    assert payload["sample_fixtures"][0]["status_label"] == "未开赛"
    assert payload["errors"] == []


def test_recommendations_today_filters_pass_and_sorts_by_score() -> None:
    app.dependency_overrides[recommendations_router.get_prediction_pipeline] = lambda: _fake_recommendation_pipeline()
    try:
        client = TestClient(app)
        response = client.get("/api/recommendations/today")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 3
    assert [item["signal"] for item in payload["items"]] == ["STRONG_BUY", "BUY", "WATCH"]
    assert [item["hunter_score"] for item in payload["items"]] == [91.0, 88.0, 79.0]
    assert payload["items"][0]["stake"] == "2U"
    assert payload["items"][0]["odds"]["bookmaker"] == "DebugBook"
    assert payload["items"][0]["score_prediction"]["text"] == "2-1"
    assert payload["items"][0]["total_goals"]["label"] == "大 2.5"
    assert payload["items"][0]["handicap"]["label"] == "主队 -0.25"
    assert "market_available" in payload["items"][0]["total_goals"]


def test_today_recommendations_skip_finished_fixtures() -> None:
    pipeline = _fake_recommendation_pipeline()
    results = pipeline.run_today()
    results[0].fixture.status = FixtureStatus.FINISHED

    class FinishedAwarePipeline:
        context = pipeline.context

        def run_today(self) -> list:
            return results

    payload = build_today_recommendations(FinishedAwarePipeline(), include_pass=True, archive=False)

    assert payload["count"] == 3
    assert all(item["fixture_status"] != FixtureStatus.FINISHED.value for item in payload["items"])


def test_today_recommendations_only_include_beijing_today_upcoming_or_live() -> None:
    pipeline = _fake_recommendation_pipeline()
    results = pipeline.run_today()
    now = datetime.now(timezone.utc)
    results[0].fixture.start_time = _future_beijing_today_start()
    results[1].fixture.start_time = _tomorrow_beijing_start()
    results[2].fixture.start_time = now - timedelta(minutes=1)
    results[3].fixture.status = FixtureStatus.LIVE
    results[3].fixture.start_time = _recent_beijing_today_start()

    class WindowAwarePipeline:
        context = pipeline.context

        def run_today(self) -> list:
            return results

    payload = build_today_recommendations(WindowAwarePipeline(), include_pass=True, archive=False)

    assert payload["count"] == 2
    assert [item["fixture_id"] for item in payload["items"]] == ["strong", "buy"]


def test_recommendations_today_can_include_pass() -> None:
    app.dependency_overrides[recommendations_router.get_prediction_pipeline] = lambda: _fake_recommendation_pipeline()
    try:
        client = TestClient(app)
        response = client.get("/api/recommendations/today?include_pass=true")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 4
    assert [item["signal"] for item in payload["items"]] == ["STRONG_BUY", "BUY", "WATCH", "PASS"]


def test_telegram_message_for_empty_recommendations() -> None:
    message = format_recommendations_message({"count": 0, "items": []})
    assert "SportsHunter AI 今日推荐" in message
    assert "今日没有符合条件的推荐。" in message


def test_telegram_message_formats_recommendations() -> None:
    message = format_recommendations_message(
        {
            "count": 1,
            "items": [
                {
                    "league": "Brazilian Serie B",
                    "match": "Atlético Goianiense vs Operário PR",
                    "kickoff": "2026-07-26T12:00:00+00:00",
                    "hunter_score": 91.0,
                    "confidence": 0.91,
                    "signal": "BUY",
                    "predicted_side": "Atlético Goianiense",
                    "stake": "2U",
                    "reason": "Debug reason",
                    "odds": {},
                    "market_prediction": _fake_market_prediction("Atlético Goianiense").to_dict(),
                }
            ],
        }
    )
    assert "戈亚尼亚竞技 对阵 欧帕瑞欧" in message
    assert "联赛：巴西乙级联赛" in message
    assert "信号：推荐" in message
    assert "推荐方向：戈亚尼亚竞技" in message
    assert "仓位：2U" in message
    assert "开赛时间：2026-07-26 20:00 北京时间" in message
    assert "\n模型预测：" in message
    assert "比分预测：2-1" in message
    assert "大小球：大 2.5" in message
    assert "让球：戈亚尼亚竞技 -0.25" in message
    assert "水位 主" in message
    assert "信号：推荐 | 猎手评分" not in message
    assert "推荐方向：戈亚尼亚竞技 | 仓位" not in message


def test_telegram_test_api_sends_test_message(monkeypatch) -> None:
    sent_messages: list[str] = []

    class FakeNotifier:
        async def send_message_with_result(self, text: str) -> TelegramSendResult:
            sent_messages.append(text)
            return TelegramSendResult(success=True, sent=True, message_id=123)

    monkeypatch.setattr(telegram_router, "TelegramNotifier", FakeNotifier)
    response = TestClient(app).post("/api/telegram/test")
    assert response.status_code == 200
    assert response.json() == {"success": True, "sent": True, "message_id": 123}
    assert sent_messages == ["SportsHunter AI 测试消息"]


def test_telegram_test_api_does_not_return_500_when_send_fails(monkeypatch) -> None:
    class FakeNotifier:
        async def send_message_with_result(self, text: str) -> TelegramSendResult:
            raise RuntimeError("telegram api failed")

    monkeypatch.setattr(telegram_router, "TelegramNotifier", FakeNotifier)
    response = TestClient(app).post("/api/telegram/test")
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["sent"] is False
    assert payload["error_code"] == "INTERNAL_ERROR"
    assert "Telegram 测试发送异常" in payload["error"]


def test_telegram_status_api_returns_diagnostics(monkeypatch) -> None:
    class FakeNotifier:
        async def health_check(self) -> dict:
            return {"provider": "telegram", "health": "ok", "config": {"ready": True}, "error": None}

    monkeypatch.setattr(telegram_router, "TelegramNotifier", FakeNotifier)
    response = TestClient(app).get("/api/telegram/status")
    assert response.status_code == 200
    assert response.json()["provider"] == "telegram"
    assert response.json()["config"]["ready"] is True


def test_telegram_command_help_lists_interactive_commands() -> None:
    text = command_help_text()
    assert "/status" in text
    assert "/today" in text
    assert "/recommendations" in text
    assert "/alerts" in text
    assert "/report" in text


def test_telegram_command_status_message_is_chinese() -> None:
    text = format_status_message(
        {
            "health": "not_ready",
            "config": {
                "enabled": True,
                "ready": False,
                "bot_token_configured": True,
                "chat_id_configured": False,
                "warnings": ["缺少 CHAT_ID 或 TELEGRAM_CHAT_ID。"],
            },
            "error": "缺少 CHAT_ID 或 TELEGRAM_CHAT_ID。",
        }
    )
    assert "SportsHunter AI 状态" in text
    assert "配置就绪：False" in text
    assert "缺少 CHAT_ID" in text


def test_telegram_alert_push_reply_summarizes_result() -> None:
    text = format_alert_push_reply(
        {
            "success": True,
            "sent": False,
            "evaluated_count": 6,
            "eligible_count": 0,
            "pushed_count": 0,
            "skipped_count": 0,
            "message": "没有新的合适比赛，未发送 Telegram。",
            "error": None,
        }
    )
    assert "机会检查" in text
    assert "评估场次：6" in text
    assert "符合场次：0" in text


def test_telegram_notifier_reports_missing_config() -> None:
    import asyncio

    settings = Settings(telegram_enabled=True, bot_token="", chat_id="", _env_file=None)
    notifier = TelegramNotifier(settings)
    result = asyncio.run(notifier.send_message_with_result("测试"))
    assert result.sent is False
    assert result.error_code == "CONFIG_NOT_READY"
    assert result.error is not None
    assert "缺少 BOT_TOKEN" in result.error
    assert "缺少 CHAT_ID" in result.error


def test_telegram_notifier_rejects_bot_chat_id() -> None:
    settings = Settings(
        telegram_enabled=True,
        bot_token="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        chat_id="123456789",
        _env_file=None,
    )
    status = TelegramNotifier(settings).config_status()
    assert status.ready is False
    assert any("CHAT_ID 不能填写机器人自身 ID" in warning for warning in status.warnings)


def test_telegram_localizes_current_fixture_team_names() -> None:
    assert translate_team_name("Atlético Goianiense") == "戈亚尼亚竞技"
    assert translate_team_name("Operário PR") == "欧帕瑞欧"
    assert translate_team_name("CRB") == "雷加塔斯巴西"
    assert translate_team_name("Vila Nova") == "维拉诺瓦"
    assert translate_team_name("Sport") == "累西腓体育"
    assert translate_team_name("Cuiabá") == "库亚巴"
    assert translate_team_name("Atlanta") == "亚特兰大竞技"
    assert translate_team_name("Almagro") == "阿尔马格罗"
    assert translate_match_text("CRB vs Vila Nova") == "雷加塔斯巴西 对阵 维拉诺瓦"


def test_telegram_localizes_expanded_fixture_team_names() -> None:
    assert translate_team_name("Randers FC") == "兰讷斯"
    assert translate_team_name("Silkeborg IF") == "锡尔克堡"
    assert translate_team_name("Rosenborg") == "罗森博格"
    assert translate_team_name("Fredrikstad") == "腓特烈斯塔"
    assert translate_team_name("BK Häcken") == "赫根"
    assert translate_team_name("Galatasaray") == "加拉塔萨雷"
    assert translate_team_name("Timor-Leste") == "东帝汶"
    assert translate_team_name("Universidad Católica (Quito)") == "基多天主教大学"
    assert translate_team_name("Unión La Calera") == "拉卡莱拉联合"
    assert translate_match_text("Stabæk vs Hødd") == "斯塔贝克 对阵 霍德"




def test_localization_hot_dictionary_covers_expanded_provider_names() -> None:
    assert translate_team_name("CSKA Sofia") == "\u7d22\u83f2\u4e9a\u4e2d\u592e\u9646\u519b"
    assert translate_team_name("FK Qarabag") == "\u5361\u62c9\u5df4\u8d6b"
    assert translate_team_name("Hibernian") == "\u5e0c\u4f2f\u5c3c\u5b89"
    assert translate_match_text("FC Koper vs NSI Runavik") == "\u79d1\u4f69\u5c14 \u5bf9\u9635 \u9c81\u7eb3\u7ef4\u514b"


def test_localization_auto_translation_uses_cache(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "translation_cache.json"
    calls = []

    def fake_remote_translate(value: str) -> str:
        calls.append(value)
        return "\u81ea\u52a8\u7ffb\u8bd1\u7403\u961f"

    monkeypatch.setenv("AUTO_TRANSLATION_ENABLED", "true")
    monkeypatch.setenv("TRANSLATION_CACHE_PATH", str(cache_path))
    monkeypatch.setattr(localization_module, "_remote_translate_label", fake_remote_translate)
    localization_module._reset_translation_cache_for_tests()

    assert translate_team_name("Neverland United FC") == "\u81ea\u52a8\u7ffb\u8bd1\u7403\u961f"
    assert translate_team_name("Neverland United FC") == "\u81ea\u52a8\u7ffb\u8bd1\u7403\u961f"
    assert calls == ["Neverland United FC"]
    assert cache_path.exists()

    localization_module._reset_translation_cache_for_tests()
    monkeypatch.setenv("AUTO_TRANSLATION_ENABLED", "false")


def test_telegram_fixtures_message_formats_real_fixtures() -> None:
    league = League(id="bra.2", name="Brazilian Serie B", provider="free")
    fixture = Fixture(
        id="fixture-1",
        league=league,
        home_team=Team(id="home", name="Atlético Goianiense", provider="free"),
        away_team=Team(id="away", name="Operário PR", provider="free"),
        start_time=datetime(2026, 7, 27, 22, 30, tzinfo=timezone.utc),
        status=FixtureStatus.SCHEDULED,
        score=Score(),
        provider="free",
    )

    message = format_fixtures_message([fixture])

    assert "SportsHunter AI 今日真实赛程" in message
    assert "比赛数量：1" in message
    assert "戈亚尼亚竞技 对阵 欧帕瑞欧" in message
    assert "巴西乙级联赛（bra.2）" in message
    assert "开赛时间：2026-07-28 06:30 北京时间" in message


def test_telegram_today_fixtures_api_pushes_datahub_fixtures(monkeypatch) -> None:
    sent_messages: list[str] = []
    league = League(id="arg.2", name="Argentine Primera Nacional", provider="free")
    fixture = Fixture(
        id="fixture-2",
        league=league,
        home_team=Team(id="home", name="Atlanta", provider="free"),
        away_team=Team(id="away", name="Almagro", provider="free"),
        start_time=datetime(2026, 7, 27, 23, 0, tzinfo=timezone.utc),
        status=FixtureStatus.SCHEDULED,
        score=Score(),
        provider="free",
    )

    class FakeDataHub:
        def get_today_fixtures(self) -> list[Fixture]:
            return [fixture]

    class FakeNotifier:
        async def send_message(self, text: str) -> bool:
            sent_messages.append(text)
            return True

    monkeypatch.setattr(telegram_router, "TelegramNotifier", FakeNotifier)
    app.dependency_overrides[telegram_router.get_datahub] = lambda: FakeDataHub()
    try:
        response = TestClient(app).post("/api/telegram/fixtures/today")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["sent"] is True
    assert response.json()["count"] == 1
    assert response.json()["error"] is None
    assert "亚特兰大竞技 对阵 阿尔马格罗" in sent_messages[0]


def test_telegram_today_recommendations_api_pushes_recommendations(monkeypatch) -> None:
    sent_messages: list[str] = []

    class FakeNotifier:
        async def send_message(self, text: str) -> bool:
            sent_messages.append(text)
            return True

    monkeypatch.setattr(telegram_router, "TelegramNotifier", FakeNotifier)
    app.dependency_overrides[telegram_router.get_prediction_pipeline] = lambda: _fake_recommendation_pipeline()
    try:
        response = TestClient(app).post("/api/telegram/recommendations/today")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["sent"] is True
    assert payload["count"] == 3
    assert "SportsHunter AI 今日推荐" in sent_messages[0]
    assert "信号：强烈推荐" in sent_messages[0]


def test_telegram_alert_pusher_sends_only_new_suitable_matches(tmp_path) -> None:
    import asyncio

    sent_messages: list[str] = []

    class FakeNotifier:
        async def send_message_with_result(self, text: str) -> TelegramSendResult:
            sent_messages.append(text)
            return TelegramSendResult(success=True, sent=True, message_id=len(sent_messages))

    settings = Settings(
        data_provider="mock",
        telegram_alert_signals=["STRONG_BUY", "BUY", "WATCH"],
        telegram_alert_archive_path=tmp_path / "alerts.json",
        _env_file=None,
    )
    pusher = RecommendationAlertPusher(
        pipeline=_fake_recommendation_pipeline(),
        notifier=FakeNotifier(),
        archive=AlertArchive(settings.telegram_alert_archive_path),
        prediction_archive=_FakePredictionArchive(),
        settings=settings,
        gate=RecommendationGate(settings, history_rows=[]),
    )

    first = asyncio.run(pusher.push_new())
    second = asyncio.run(pusher.push_new())

    assert first.success is True
    assert first.sent is True
    assert first.evaluated_count == 4
    assert first.eligible_count == 2
    assert first.pushed_count == 2
    assert second.success is True
    assert second.sent is False
    assert second.pushed_count == 0
    assert second.skipped_count == 2
    assert len(sent_messages) == 2
    assert all("SportsHunter AI 发现合适比赛" in message for message in sent_messages)


def test_telegram_alert_pusher_skips_already_started_matches(tmp_path) -> None:
    import asyncio

    sent_messages: list[str] = []
    base_pipeline = _fake_recommendation_pipeline()
    prediction_archive = _FakePredictionArchive()

    class FakeNotifier:
        async def send_message_with_result(self, text: str) -> TelegramSendResult:
            sent_messages.append(text)
            return TelegramSendResult(success=True, sent=True, message_id=len(sent_messages))

    class MixedPipeline:
        context = base_pipeline.context

        def run_today(self) -> list:
            results = base_pipeline.run_today()
            results[0].fixture.start_time = _future_beijing_today_start()
            results[0].fixture.status = FixtureStatus.SCHEDULED
            results[1].fixture.start_time = _recent_beijing_today_start(minutes=5)
            results[1].fixture.status = FixtureStatus.SCHEDULED
            results[3].fixture.start_time = _recent_beijing_today_start(minutes=90)
            results[3].fixture.status = FixtureStatus.LIVE
            return results

    settings = Settings(
        data_provider="mock",
        telegram_alert_signals=["STRONG_BUY", "BUY", "WATCH"],
        telegram_alert_archive_path=tmp_path / "alerts.json",
        _env_file=None,
    )
    pusher = RecommendationAlertPusher(
        pipeline=MixedPipeline(),
        notifier=FakeNotifier(),
        archive=AlertArchive(settings.telegram_alert_archive_path),
        prediction_archive=prediction_archive,
        settings=settings,
        gate=RecommendationGate(settings, history_rows=[]),
    )

    result = asyncio.run(pusher.push_new())

    assert result.success is True
    assert result.sent is True
    assert result.evaluated_count == 4
    assert result.eligible_count == 1
    assert result.pushed_count == 1
    assert len(sent_messages) == 1
    assert [item.fixture.id for item in prediction_archive.saved] == ["buy"]


def test_telegram_alert_message_formats_single_prediction() -> None:
    pipeline = _fake_recommendation_pipeline()
    result = pipeline.run_today()[0]
    message = format_recommendation_alert_message(pipeline, result)
    assert "SportsHunter AI 发现合适比赛" in message
    assert "信号：推荐" in message
    assert "仓位：1.5U" in message
    assert "比分预测：2-1" in message
    assert "大小球：大 2.5" in message
    assert "让球：" in message
    assert "-0.25" in message
    assert "Debug Home" not in message
    assert "赔率：DebugBook" in message


def test_telegram_alert_check_api_pushes_new_recommendations(monkeypatch, tmp_path) -> None:
    sent_messages: list[str] = []

    class FakeNotifier:
        async def send_message_with_result(self, text: str) -> TelegramSendResult:
            sent_messages.append(text)
            return TelegramSendResult(success=True, sent=True, message_id=len(sent_messages))

    class FakePusher:
        def __init__(self, pipeline, notifier) -> None:
            self.pusher = RecommendationAlertPusher(
                pipeline=pipeline,
                notifier=FakeNotifier(),
                archive=AlertArchive(tmp_path / "api-alerts.json"),
                prediction_archive=_FakePredictionArchive(),
                settings=Settings(
                    data_provider="mock",
                    telegram_alert_signals=["STRONG_BUY", "BUY", "WATCH"],
                    telegram_alert_archive_path=tmp_path / "api-alerts.json",
                    _env_file=None,
                ),
                gate=RecommendationGate(
                    Settings(data_provider="mock", telegram_alert_archive_path=tmp_path / "api-alerts.json", _env_file=None),
                    history_rows=[],
                ),
            )

        async def push_new(self):
            return await self.pusher.push_new()

    monkeypatch.setattr(telegram_router, "RecommendationAlertPusher", FakePusher)
    app.dependency_overrides[telegram_router.get_prediction_pipeline] = lambda: _fake_recommendation_pipeline()
    try:
        response = TestClient(app).post("/api/telegram/alerts/check")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["sent"] is True
    assert payload["pushed_count"] == 2
    assert len(sent_messages) == 2


def test_scheduler_registers_triggered_telegram_alert_job() -> None:
    scheduler = create_scheduler()
    jobs_by_id = {job.id: job for job in scheduler.get_jobs()}
    assert "archive_today_predictions" in jobs_by_id
    assert "telegram_recommendation_alerts" in jobs_by_id
    assert "model_optimizer_check" in jobs_by_id
    assert "telegram_daily_recommendations" not in jobs_by_id
    assert "interval[0:30:00]" in str(jobs_by_id["save_results"].trigger)
    assert "cron[hour='10', minute='0']" in str(jobs_by_id["daily_report"].trigger)
    if scheduler.running:
        scheduler.shutdown(wait=False)


def test_telegram_alert_job_returns_push_result(monkeypatch) -> None:
    class FakePusher:
        async def push_new(self):
            return SimpleNamespace(to_dict=lambda: {"sent": True, "pushed_count": 1, "message": "ok"})

    monkeypatch.setattr(jobs, "RecommendationAlertPusher", FakePusher)
    assert jobs.telegram_recommendation_alerts() == {"sent": True, "pushed_count": 1, "message": "ok"}


def test_archive_today_predictions_job_returns_archive_summary(monkeypatch) -> None:
    class FakePipeline:
        def run_today(self) -> list:
            return ["prediction"]

    class FakeArchive:
        def save_many_if_changed(self, results: list) -> SimpleNamespace:
            assert results == ["prediction"]
            return SimpleNamespace(to_dict=lambda: {"created_count": 1, "reused_count": 0, "failed_count": 0})

    monkeypatch.setattr(jobs, "PredictionPipeline", FakePipeline)
    monkeypatch.setattr(jobs, "PredictionArchive", FakeArchive)

    assert jobs.archive_today_predictions() == {"created_count": 1, "reused_count": 0, "failed_count": 0}




def test_dashboard_frontend_shows_recommendation_summary() -> None:
    script = Path("dashboard/static/app.js").read_text(encoding="utf-8")
    template = Path("dashboard/templates/index.html").read_text(encoding="utf-8")

    assert 'id="recommendation-summary"' in template
    assert "function renderRecommendationSummary" in script
    assert "\\u5f53\\u524d\\u7b5b\\u9009" in script
    assert "itemMatchText" in script


def test_dashboard_frontend_exposes_period_stats_controls() -> None:
    script = Path("dashboard/static/app.js").read_text(encoding="utf-8")
    template = Path("dashboard/templates/index.html").read_text(encoding="utf-8")

    assert 'data-period-control="analytics"' in template
    assert 'data-period-control="evaluation"' in template
    assert 'id="dashboard-summary-link"' in template
    assert "function renderPeriodControls" in script
    assert "period_days=${encodeURIComponent(state.periodDays)}" in script
    assert "handlePeriodControlClick" in script


def test_dashboard_frontend_shows_kickoff_distance() -> None:
    script = Path("dashboard/static/app.js").read_text(encoding="utf-8")

    assert "function formatKickoffDistance" in script
    assert "\\u8ddd\\u5f00\\u8d5b" in script
    assert "\\u5373\\u5c06\\u5f00\\u8d5b" in script


def test_dashboard_frontend_uses_beijing_time_for_filters_and_export() -> None:
    script = Path("dashboard/static/app.js").read_text(encoding="utf-8")

    assert "function beijingDateKey" in script
    assert 'timeZone: "Asia/Shanghai"' in script
    assert 'formatKickoffFull(item.kickoff)' in script


def test_dashboard_frontend_formats_kickoff_as_beijing_time() -> None:
    script = Path("dashboard/static/app.js").read_text(encoding="utf-8")

    assert 'timeZone: "Asia/Shanghai"' in script


def test_dashboard_frontend_localizes_legacy_report_league_names() -> None:
    script = Path("dashboard/static/app.js").read_text(encoding="utf-8")
    template = Path("dashboard/templates/index.html").read_text(encoding="utf-8")
    assert "function translateLeagueName" in script
    assert "target[translateLeagueName(name.trim())]" in script
    assert "Argentine Liga Profesional de Futbol" in script
    assert "\\u963f\\u6839\\u5ef7\\u7532\\u7ea7\\u8054\\u8d5b" in script
    assert "20260810-odds-evidence" in template
    assert "odds-quality-performance" in template
    assert "clv-performance" in template
    assert "odds-freshness-performance" in template
    assert "function formatSignedPercent" in script
    assert "function translateOddsFreshness" in script

def test_provider_debug_api_returns_diagnostic_payload(mock_settings) -> None:
    app.dependency_overrides[provider_router.get_datahub] = lambda: DataHub(MockProvider(mock_settings))
    try:
        client = TestClient(app)
        response = client.get("/api/provider/debug")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "mock"
    assert payload["request_url"] == "mock://today"
    assert payload["http_status"] == 200
    assert payload["leagues_checked"] == ["mock"]
    assert payload["fixtures_per_league"] == {"mock": 1}
    assert payload["fixtures_raw"] == 1
    assert payload["fixtures_parsed"] == 1
    assert payload["first_fixture"]["id"] == "mock-001"
    assert payload["errors"] == []


def test_free_provider_debug_parses_raw_scoreboard(monkeypatch) -> None:
    payload = {
        "leagues": [{"name": "English Premier League"}],
        "events": [
            {
                "id": "401",
                "date": "2026-07-26T12:00:00Z",
                "season": {"slug": "regular-season"},
                "competitions": [
                    {
                        "venue": {"fullName": "Debug Stadium"},
                        "status": {
                            "type": {"state": "pre", "name": "STATUS_SCHEDULED", "detail": "Scheduled"},
                            "displayClock": "",
                        },
                        "competitors": [
                            {
                                "homeAway": "home",
                                "score": "0",
                                "team": {"id": "1", "displayName": "Debug Home", "abbreviation": "DHM"},
                            },
                            {
                                "homeAway": "away",
                                "score": "0",
                                "team": {"id": "2", "displayName": "Debug Away", "abbreviation": "DAW"},
                            },
                        ],
                    }
                ],
            }
        ],
    }

    class FakeResponse:
        status_code = 200
        url = "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard?dates=20260726"

        def json(self) -> dict:
            return payload

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args) -> None:
            return None

        def get(self, *args, **kwargs) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr("free_provider.football.httpx.Client", FakeClient)
    settings = Settings(
        data_provider="free",
        free_provider_sources=["espn"],
        free_provider_football_leagues=["eng.1"],
        _env_file=None,
    )
    debug = FreeFootballProvider(settings).debug_today()
    assert debug["provider"] == "free"
    assert debug["http_status"] == 200
    assert debug["leagues_checked"] == ["eng.1"]
    assert debug["fixtures_per_league"] == {"eng.1": 1}
    assert debug["fixtures_raw"] == 1
    assert debug["fixtures_parsed"] == 1
    assert debug["first_fixture"]["home_team"]["name"] == "Debug Home"
    assert debug["errors"] == []


def test_free_provider_debug_checks_multiple_leagues(monkeypatch) -> None:
    payloads = {
        "eng.1": _scoreboard_payload("eng.1", []),
        "esp.1": _scoreboard_payload("esp.1", ["700", "701"]),
        "ger.1": _scoreboard_payload("ger.1", ["700"]),
    }

    class FakeResponse:
        status_code = 200

        def __init__(self, league_id: str) -> None:
            self.league_id = league_id
            self.url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league_id}/scoreboard?dates=20260726"

        def json(self) -> dict:
            return payloads[self.league_id]

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args) -> None:
            return None

        def get(self, url: str, *args, **kwargs) -> FakeResponse:
            league_id = next(league for league in payloads if f"/{league}/" in url)
            return FakeResponse(league_id)

    monkeypatch.setattr("free_provider.football.httpx.Client", FakeClient)
    settings = Settings(
        data_provider="free",
        free_provider_sources=["espn"],
        free_provider_football_leagues=["eng.1", "esp.1", "ger.1"],
        _env_file=None,
    )
    debug = FreeFootballProvider(settings).debug_today()
    assert debug["leagues_checked"] == ["eng.1", "esp.1", "ger.1"]
    assert debug["fixtures_per_league"] == {"eng.1": 0, "esp.1": 2, "ger.1": 1}
    assert debug["fixtures_raw"] == 3
    assert debug["fixtures_parsed"] == 2
    assert debug["first_fixture"]["id"] == "700"
    assert len(debug["request_urls"]) == 3


def test_free_provider_today_aggregates_leagues_and_deduplicates() -> None:
    payloads = {
        "eng.1": _scoreboard_payload("eng.1", []),
        "esp.1": _scoreboard_payload("esp.1", ["800", "801"]),
        "ger.1": _scoreboard_payload("ger.1", ["800"]),
    }

    class FakeJsonClient:
        def get_json(self, path: str, params: dict | None = None) -> dict:
            league_id = next(league for league in payloads if f"/{league}/" in path)
            return payloads[league_id]

    settings = Settings(
        data_provider="free",
        free_provider_sources=["espn"],
        free_provider_football_leagues=["eng.1", "esp.1", "ger.1", "esp.1"],
        _env_file=None,
    )
    provider = FreeFootballProvider(settings)
    provider.client = FakeJsonClient()
    fixtures = provider.get_today_fixtures()
    assert [fixture.id for fixture in fixtures] == ["800", "801"]
    assert {fixture.league.id for fixture in fixtures} == {"esp.1"}


def test_free_provider_maps_espn_postponed_status_without_finished_score() -> None:
    payload = _scoreboard_payload("bra.1", ["postponed-1"])
    competition = payload["events"][0]["competitions"][0]
    competition["status"]["type"] = {
        "id": "6",
        "state": "post",
        "name": "STATUS_POSTPONED",
        "description": "Postponed",
        "detail": "Postponed",
        "completed": False,
    }

    settings = Settings(
        data_provider="free",
        free_provider_sources=["espn"],
        free_provider_football_leagues=["bra.1"],
        _env_file=None,
    )
    provider = FreeFootballProvider(settings)
    fixture = provider._parse_scoreboard("bra.1", payload)[0]

    assert fixture.status == FixtureStatus.POSTPONED
    assert fixture.score is not None
    assert fixture.score.home is None
    assert fixture.score.away is None


def test_free_provider_odds_parses_totals_and_handicap() -> None:
    class FakeJsonClient:
        def get_json(self, path: str, params: dict | None = None) -> dict:
            if path.endswith("/summary"):
                return _summary_odds_payload()
            return _scoreboard_payload("eng.1", ["odds-1"])

    settings = Settings(
        data_provider="free",
        free_provider_sources=["espn"],
        free_provider_football_leagues=["eng.1"],
        _env_file=None,
    )
    provider = FreeFootballProvider(settings)
    provider.client = FakeJsonClient()

    odds = provider.get_odds("odds-1")

    assert [item.market for item in odds] == [
        OddsMarket.EUROPEAN,
        OddsMarket.TOTALS,
        OddsMarket.ASIAN_HANDICAP,
    ]
    assert odds[1].line == 2.5
    assert odds[1].over == -115
    assert odds[1].under == 105
    assert odds[2].line == -0.5
    assert odds[2].home == -140
    assert odds[2].away == 100


def test_free_provider_prepends_the_odds_api_bookmaker_odds() -> None:
    captured_params: dict[str, str] = {}

    class FakeJsonClient:
        def get_json(self, path: str, params: dict | None = None) -> dict:
            if path.endswith("/summary"):
                return _summary_odds_payload()
            return _scoreboard_payload("eng.1", ["odds-1"])

    class FakeOddsApiClient:
        def get_json(self, path: str, params: dict | None = None) -> list[dict]:
            captured_params.update(params or {})
            assert path == "/v4/sports/soccer_epl/odds"
            return _the_odds_api_payload()

    settings = Settings(
        data_provider="free",
        free_provider_sources=["espn"],
        free_provider_football_leagues=["eng.1"],
        odds_aggregator_enabled=True,
        the_odds_api_key="test-key",
        the_odds_api_regions=["uk", "eu"],
        _env_file=None,
    )
    provider = FreeFootballProvider(settings)
    provider.client = FakeJsonClient()
    assert provider.odds_aggregator is not None
    provider.odds_aggregator.client = FakeOddsApiClient()

    odds = provider.get_odds("odds-1")

    assert [item.market for item in odds[:3]] == [
        OddsMarket.EUROPEAN,
        OddsMarket.TOTALS,
        OddsMarket.ASIAN_HANDICAP,
    ]
    assert all(item.provider == "the_odds_api" for item in odds[:3])
    assert odds[0].bookmaker == "Pinnacle"
    assert odds[0].home == 1.83
    assert odds[0].draw == 3.55
    assert odds[0].away == 4.4
    assert odds[1].line == 2.75
    assert odds[1].over == 1.95
    assert odds[1].under == 1.9
    assert odds[2].line == -0.25
    assert odds[2].home == 2.0
    assert odds[2].away == 1.85
    assert odds[3].provider == "free"
    assert captured_params["markets"] == "h2h,spreads,totals"
    assert captured_params["regions"] == "uk,eu"


def test_free_provider_prepends_api_football_bookmaker_odds() -> None:
    ApiFootballOddsProvider.clear_shared_state()
    captured_calls: list[tuple[str, dict[str, str]]] = []

    class FakeJsonClient:
        def get_json(self, path: str, params: dict | None = None) -> dict:
            if path.endswith("/summary"):
                return _summary_odds_payload()
            return _scoreboard_payload("eng.1", ["odds-1"])

    class FakeApiFootballClient:
        def get_json(self, path: str, params: dict | None = None) -> dict:
            captured_calls.append((path, dict(params or {})))
            if path == "/fixtures":
                return _api_football_fixtures_payload()
            if path == "/odds":
                return _api_football_odds_payload()
            msg = f"unexpected API-Football path {path}"
            raise AssertionError(msg)

    settings = Settings(
        data_provider="free",
        free_provider_sources=["espn"],
        free_provider_football_leagues=["eng.1"],
        odds_aggregator_enabled=True,
        odds_aggregator_provider="api_football",
        api_football_key="test-key",
        _env_file=None,
    )
    provider = FreeFootballProvider(settings)
    provider.client = FakeJsonClient()
    assert provider.odds_aggregator is not None
    provider.odds_aggregator.now = lambda: datetime(2026, 7, 26, 11, 0, tzinfo=timezone.utc)
    provider.odds_aggregator.client = FakeApiFootballClient()

    odds = provider.get_odds("odds-1")

    assert [item.market for item in odds[:3]] == [
        OddsMarket.EUROPEAN,
        OddsMarket.TOTALS,
        OddsMarket.ASIAN_HANDICAP,
    ]
    assert all(item.provider == "api_football" for item in odds[:3])
    assert odds[0].bookmaker == "Bwin"
    assert odds[0].home == 1.91
    assert odds[0].draw == 3.2
    assert odds[0].away == 4.1
    assert odds[1].line == 2.5
    assert odds[1].over == 1.88
    assert odds[1].under == 1.98
    assert odds[2].line == -0.25
    assert odds[2].home == 1.93
    assert odds[2].away == 1.87
    assert odds[3].provider == "free"
    assert captured_calls[0] == ("/fixtures", {"date": "2026-07-26", "timezone": "UTC"})
    assert captured_calls[1] == ("/odds", {"fixture": "1001"})


def test_api_football_skips_far_prematch_odds() -> None:
    ApiFootballOddsProvider.clear_shared_state()
    calls: list[str] = []
    now = datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc)
    fixture = Fixture(
        id="far-fixture",
        league=League(id="eng.1", name="Premier League"),
        home_team=Team(id="home", name="Home"),
        away_team=Team(id="away", name="Away"),
        start_time=now + timedelta(hours=4),
        status=FixtureStatus.SCHEDULED,
    )

    class FakeApiFootballClient:
        def get_json(self, path: str, params: dict | None = None) -> dict:
            calls.append(path)
            return {}

    provider = ApiFootballOddsProvider(
        Settings(
            odds_aggregator_enabled=True,
            odds_aggregator_provider="api_football",
            api_football_key="test-key",
            api_football_prematch_window_minutes=90,
            _env_file=None,
        ),
        client=FakeApiFootballClient(),
    )
    provider.now = lambda: now

    assert provider.get_odds(fixture) == []
    assert calls == []


def test_api_football_caches_near_prematch_odds() -> None:
    ApiFootballOddsProvider.clear_shared_state()
    calls: list[str] = []
    now = datetime(2026, 7, 26, 11, 0, tzinfo=timezone.utc)
    fixture = Fixture(
        id="odds-1",
        league=League(id="eng.1", name="Premier League"),
        home_team=Team(id="home", name="eng.1 Home odds-1"),
        away_team=Team(id="away", name="eng.1 Away odds-1"),
        start_time=datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc),
        status=FixtureStatus.SCHEDULED,
    )

    class FakeApiFootballClient:
        def get_json(self, path: str, params: dict | None = None) -> dict:
            calls.append(path)
            if path == "/fixtures":
                return _api_football_fixtures_payload()
            if path == "/odds":
                return _api_football_odds_payload()
            raise AssertionError(path)

    provider = ApiFootballOddsProvider(
        Settings(
            odds_aggregator_enabled=True,
            odds_aggregator_provider="api_football",
            api_football_key="test-key",
            api_football_prematch_cache_ttl_seconds=1800,
            _env_file=None,
        ),
        client=FakeApiFootballClient(),
    )
    provider.now = lambda: now

    assert provider.get_odds(fixture)
    assert provider.get_odds(fixture)
    assert calls == ["/fixtures", "/odds"]


def test_api_football_quota_error_suppresses_followup_requests() -> None:
    ApiFootballOddsProvider.clear_shared_state()
    calls: list[str] = []
    now = datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc)
    fixture = Fixture(
        id="quota-fixture",
        league=League(id="eng.1", name="Premier League"),
        home_team=Team(id="home", name="Home"),
        away_team=Team(id="away", name="Away"),
        start_time=now + timedelta(minutes=30),
        status=FixtureStatus.SCHEDULED,
    )

    class FakeApiFootballClient:
        def get_json(self, path: str, params: dict | None = None) -> dict:
            calls.append(path)
            return {"errors": {"requests": "You have reached the request limit for the day"}}

    provider = ApiFootballOddsProvider(
        Settings(
            odds_aggregator_enabled=True,
            odds_aggregator_provider="api_football",
            api_football_key="test-key",
            _env_file=None,
        ),
        client=FakeApiFootballClient(),
    )
    provider.now = lambda: now

    assert provider.get_odds(fixture) == []
    assert provider.get_odds(fixture) == []
    assert calls == ["/fixtures"]
    ApiFootballOddsProvider.clear_shared_state()


def test_free_provider_today_aggregates_supplemental_sources_and_deduplicates() -> None:
    class FakeEspnClient:
        def get_json(self, path: str, params: dict | None = None) -> dict:
            return _scoreboard_payload("eng.1", ["900"])

    class FakeTheSportsDbClient:
        def get_json(self, path: str, params: dict | None = None) -> dict:
            return _thesportsdb_events_payload(
                [
                    {
                        "idEvent": "tsdb-duplicate",
                        "strHomeTeam": "eng.1 Home 900",
                        "strAwayTeam": "eng.1 Away 900",
                        "strTimestamp": "2026-07-26T12:00:00",
                    },
                    {
                        "idEvent": "tsdb-new",
                        "strHomeTeam": "Rosenborg",
                        "strAwayTeam": "Fredrikstad",
                        "strTimestamp": "2026-07-26T17:00:00",
                    },
                ]
            )

    settings = Settings(
        data_provider="free",
        free_provider_sources=["espn", "thesportsdb"],
        free_provider_football_leagues=["eng.1"],
        _env_file=None,
    )
    provider = FreeFootballProvider(settings)
    provider.client = FakeEspnClient()
    provider.thesportsdb_client = FakeTheSportsDbClient()

    fixtures = provider.get_today_fixtures()

    assert [fixture.id for fixture in fixtures] == ["900", "tsdb:tsdb-new"]
    assert fixtures[1].league.id == "tsdb:4358"
    assert fixtures[1].raw["source"] == "thesportsdb"


def test_free_provider_live_uses_thesportsdb_livescore() -> None:
    class FakeTheSportsDbClient:
        def get_json(self, path: str, params: dict | None = None) -> dict:
            if path == "/eventsday.php":
                return {"events": []}
            return _thesportsdb_live_payload()

    settings = Settings(
        data_provider="free",
        free_provider_sources=["thesportsdb"],
        _env_file=None,
    )
    provider = FreeFootballProvider(settings)
    provider.thesportsdb_client = FakeTheSportsDbClient()

    fixtures = provider.get_live_matches()

    assert len(fixtures) == 1
    assert fixtures[0].id == "tsdb:live-1"
    assert fixtures[0].status == FixtureStatus.LIVE
    assert fixtures[0].score.home == 1
    assert fixtures[0].score.away == 0


def test_free_provider_debug_reports_multiple_sources(monkeypatch) -> None:
    class FakeResponse:
        status_code = 200

        def __init__(self, url: str, payload: dict) -> None:
            self.url = url
            self._payload = payload

        def json(self) -> dict:
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args) -> None:
            return None

        def get(self, url: str, *args, **kwargs) -> FakeResponse:
            if "eventsday.php" in url:
                return FakeResponse(url, _thesportsdb_events_payload([{"idEvent": "tsdb-1"}]))
            return FakeResponse(url, _scoreboard_payload("eng.1", ["901"]))

    monkeypatch.setattr("free_provider.football.httpx.Client", FakeClient)
    settings = Settings(
        data_provider="free",
        free_provider_sources=["espn", "thesportsdb"],
        free_provider_football_leagues=["eng.1", "kor.1"],
        _env_file=None,
    )
    debug = FreeFootballProvider(settings).debug_today()

    assert debug["sources_checked"] == ["espn", "thesportsdb"]
    assert debug["leagues_configured"] == ["eng.1", "kor.1"]
    assert debug["leagues_checked"] == ["eng.1"]
    assert debug["leagues_skipped"] == ["kor.1"]
    assert debug["fixtures_per_source"] == {"espn": 1, "thesportsdb": 1}
    assert debug["fixtures_raw"] == 2
    assert debug["fixtures_parsed"] == 2


def test_refresh_live_job_serializes_slots_dataclass(monkeypatch) -> None:
    class FakeDataSync:
        def sync_live(self) -> SyncSummary:
            return SyncSummary(sync_type="live", provider="mock", synced_count=2).finish()

    monkeypatch.setattr(jobs, "DataSync", FakeDataSync)
    result = jobs.refresh_live()
    assert result["sync_type"] == "live"
    assert result["provider"] == "mock"
    assert result["synced_count"] == 2
    assert "started_at" in result


def test_risk_breakdown_serializes_slots_dataclass() -> None:
    breakdown = RiskBreakdown(items=[RiskReason(source="data_missing", score=14.0, reason="Data missing")])
    assert breakdown.to_dict() == {
        "items": [{"source": "data_missing", "score": 14.0, "reason": "Data missing"}]
    }


def _scoreboard_payload(league_id: str, event_ids: list[str]) -> dict:
    return {
        "leagues": [{"name": f"League {league_id}"}],
        "events": [
            {
                "id": event_id,
                "date": "2026-07-26T12:00:00Z",
                "season": {"slug": "regular-season"},
                "competitions": [
                    {
                        "venue": {"fullName": "Multi League Stadium"},
                        "status": {
                            "type": {"state": "pre", "name": "STATUS_SCHEDULED", "detail": "Scheduled"},
                            "displayClock": "",
                        },
                        "competitors": [
                            {
                                "homeAway": "home",
                                "score": "0",
                                "team": {
                                    "id": f"{event_id}-home",
                                    "displayName": f"{league_id} Home {event_id}",
                                    "abbreviation": "HOM",
                                },
                            },
                            {
                                "homeAway": "away",
                                "score": "0",
                                "team": {
                                    "id": f"{event_id}-away",
                                    "displayName": f"{league_id} Away {event_id}",
                                    "abbreviation": "AWY",
                                },
                            },
                        ],
                    }
                ],
            }
            for event_id in event_ids
        ],
    }


def _summary_odds_payload() -> dict:
    return {
        "pickcenter": [
            {
                "provider": {"name": "DebugBook"},
                "homeTeamOdds": {"moneyLine": -130, "spreadOdds": -140},
                "awayTeamOdds": {"moneyLine": 320, "spreadOdds": 100},
                "drawOdds": {"moneyLine": 300},
                "overUnder": 2.5,
                "overOdds": -115,
                "underOdds": 105,
                "spread": -0.5,
            }
        ]
    }


def _the_odds_api_payload() -> list[dict]:
    return [
        {
            "id": "odds-api-1",
            "sport_key": "soccer_epl",
            "commence_time": "2026-07-26T12:00:00Z",
            "home_team": "eng.1 Home odds-1",
            "away_team": "eng.1 Away odds-1",
            "bookmakers": [
                {
                    "key": "pinnacle",
                    "title": "Pinnacle",
                    "last_update": "2026-07-26T11:55:00Z",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "eng.1 Home odds-1", "price": 1.83},
                                {"name": "Draw", "price": 3.55},
                                {"name": "eng.1 Away odds-1", "price": 4.40},
                            ],
                        },
                        {
                            "key": "totals",
                            "outcomes": [
                                {"name": "Over", "price": 1.95, "point": 2.75},
                                {"name": "Under", "price": 1.90, "point": 2.75},
                            ],
                        },
                        {
                            "key": "spreads",
                            "outcomes": [
                                {"name": "eng.1 Home odds-1", "price": 2.00, "point": -0.25},
                                {"name": "eng.1 Away odds-1", "price": 1.85, "point": 0.25},
                            ],
                        },
                    ],
                }
            ],
        }
    ]


def _api_football_fixtures_payload() -> dict:
    return {
        "errors": [],
        "response": [
            {
                "fixture": {
                    "id": 1001,
                    "date": "2026-07-26T12:00:00+00:00",
                },
                "teams": {
                    "home": {"name": "eng.1 Home odds-1"},
                    "away": {"name": "eng.1 Away odds-1"},
                },
            }
        ],
    }


def _api_football_odds_payload() -> dict:
    return {
        "errors": [],
        "response": [
            {
                "fixture": {"id": 1001},
                "update": "2026-07-26T11:57:00+00:00",
                "bookmakers": [
                    {
                        "id": 6,
                        "name": "Bwin",
                        "bets": [
                            {
                                "id": 1,
                                "name": "Match Winner",
                                "values": [
                                    {"value": "Home", "odd": "1.91"},
                                    {"value": "Draw", "odd": "3.20"},
                                    {"value": "Away", "odd": "4.10"},
                                ],
                            },
                            {
                                "id": 5,
                                "name": "Goals Over/Under",
                                "values": [
                                    {"value": "Over 2.5", "odd": "1.88"},
                                    {"value": "Under 2.5", "odd": "1.98"},
                                ],
                            },
                            {
                                "id": 4,
                                "name": "Asian Handicap",
                                "values": [
                                    {"value": "Home -0.25", "odd": "1.93"},
                                    {"value": "Away +0.25", "odd": "1.87"},
                                ],
                            },
                        ],
                    }
                ],
            }
        ],
    }


def _thesportsdb_events_payload(overrides: list[dict] | None = None) -> dict:
    events = []
    for index, override in enumerate(overrides or [{"idEvent": "tsdb-1"}], start=1):
        event = {
            "idEvent": f"tsdb-{index}",
            "strSport": "Soccer",
            "idLeague": "4358",
            "strLeague": "Norwegian Eliteserien",
            "strSeason": "2026",
            "strHomeTeam": "Rosenborg",
            "strAwayTeam": "Fredrikstad",
            "idHomeTeam": "133990",
            "idAwayTeam": "134749",
            "intHomeScore": None,
            "intAwayScore": None,
            "intRound": "15",
            "strTimestamp": "2026-07-26T17:00:00",
            "strStatus": "",
            "strVenue": "Lerkendal Stadion",
        }
        event.update(override)
        events.append(event)
    return {"events": events}


def _thesportsdb_live_payload() -> dict:
    return {
        "livescore": [
            {
                "idEvent": "live-1",
                "strSport": "Soccer",
                "idLeague": "4422",
                "strLeague": "Polish Ekstraklasa",
                "strHomeTeam": "Wisla Krakow",
                "strAwayTeam": "GKS Katowice",
                "idHomeTeam": "135303",
                "idAwayTeam": "142467",
                "intHomeScore": "1",
                "intAwayScore": "0",
                "strStatus": "1H",
                "strProgress": "10",
                "strTimestamp": "2026-07-26T18:15:00",
            }
        ]
    }


def _future_beijing_today_start() -> datetime:
    now_utc = datetime.now(timezone.utc)
    beijing_now = now_utc.astimezone(ZoneInfo("Asia/Shanghai"))
    start = beijing_now + timedelta(minutes=30)
    if start.date() != beijing_now.date():
        start = beijing_now.replace(hour=23, minute=59, second=30, microsecond=0)
    if start <= beijing_now:
        start = beijing_now + timedelta(seconds=1)
    return start.astimezone(timezone.utc)


def _tomorrow_beijing_start() -> datetime:
    beijing_now = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Shanghai"))
    tomorrow = (beijing_now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    return tomorrow.astimezone(timezone.utc)


def _recent_beijing_today_start(minutes: int = 20) -> datetime:
    now_utc = datetime.now(timezone.utc)
    beijing_now = now_utc.astimezone(ZoneInfo("Asia/Shanghai"))
    start = beijing_now - timedelta(minutes=minutes)
    if start.date() != beijing_now.date():
        start = beijing_now.replace(hour=0, minute=0, second=1, microsecond=0)
    return start.astimezone(timezone.utc)


def _fake_recommendation_pipeline():
    league = League(id="debug-league", name="Debug League", provider="mock")
    home = Team(id="home", name="Debug Home", provider="mock")
    away = Team(id="away", name="Debug Away", provider="mock")

    def fixture(fixture_id: str) -> Fixture:
        return Fixture(
            id=fixture_id,
            league=league,
            home_team=home,
            away_team=away,
            start_time=_future_beijing_today_start(),
            status=FixtureStatus.SCHEDULED,
            score=Score(),
            provider="mock",
        )

    class FakeDataHub:
        def get_odds(self, fixture_id: str) -> list[Odds]:
            return [
                Odds(
                    fixture_id=fixture_id,
                    market=OddsMarket.EUROPEAN,
                    bookmaker="DebugBook",
                    home=1.80,
                    draw=3.50,
                    away=4.50,
                    provider="mock",
                )
            ]

    class FakePipeline:
        context = SimpleNamespace(datahub=FakeDataHub())

        def run_today(self) -> list:
            return [
                _fake_prediction_result(fixture("buy"), 88.0, "BUY", 1.5),
                _fake_prediction_result(fixture("watch"), 79.0, "WATCH", 0.25),
                _fake_prediction_result(fixture("pass"), 77.0, "PASS", 0),
                _fake_prediction_result(fixture("strong"), 91.0, "STRONG_BUY", 2),
            ]

    return FakePipeline()


class _FakePredictionArchive:
    def __init__(self) -> None:
        self.saved: list[object] = []

    def save(self, result: object) -> int:
        self.saved.append(result)
        return len(self.saved)


def _fake_prediction_result(fixture: Fixture, score: float, signal: str, stake: float):
    market_prediction = _fake_market_prediction(fixture.home_team.name)
    return SimpleNamespace(
        fixture=fixture,
        hunter_score=SimpleNamespace(score=score, confidence=0.91, grade="★★★★☆"),
        signal=SimpleNamespace(signal=SimpleNamespace(value=signal), stake=stake, reason=f"{signal} reason"),
        market_prediction=market_prediction,
        predicted_side=fixture.home_team.name if stake else None,
    )


def _fake_market_prediction(team: str) -> MarketPrediction:
    return MarketPrediction(
        predicted_side=team,
        moneyline_pick="HOME",
        score=ScorePrediction(home=2, away=1, expected_home_goals=1.72, expected_away_goals=0.94, text="2-1"),
        total_goals=TotalGoalsPrediction(
            line=2.5,
            pick="OVER",
            label="大 2.5",
            expected_total=2.66,
            confidence=0.58,
            reason="预期总进球高于盘口",
            edge=0.16,
            bookmaker="DebugBook",
            over_odds=-110,
            under_odds=100,
            market_available=True,
        ),
        handicap=HandicapPrediction(
            side="home",
            team=team,
            line=-0.25,
            pick="HOME_HANDICAP",
            label="主队 -0.25",
            expected_margin=0.78,
            confidence=0.69,
            reason="主队预期净胜球 0.78",
            edge=0.53,
            bookmaker="DebugBook",
            home_odds=-120,
            away_odds=105,
            market_available=True,
        ),
        notes=["debug"],
    )
