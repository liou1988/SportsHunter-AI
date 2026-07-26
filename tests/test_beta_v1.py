from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.main import app
from config.settings import Settings
from config.logging import SensitiveDataFilter
from database.base import Base
from database.models import OddsSnapshot
from database.repositories import SportsRepository
from datahub.hub import DataHub
from datahub.models import Fixture, FixtureStatus, League, Odds, OddsMarket, Score, Team
from datahub.providers.mock import MockProvider
from data_sync.models import SyncSummary
from core.risk.models import RiskBreakdown, RiskReason
from free_provider.football import FreeFootballProvider, LEAGUE_NAMES
from api.routers import provider as provider_router
from api.routers import recommendations as recommendations_router
from api.routers import telegram as telegram_router
from scheduler import jobs
from scheduler.runner import create_scheduler
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


def test_env_example_defaults_to_free_provider() -> None:
    text = Path(".env.example").read_text(encoding="utf-8")
    assert "DATA_PROVIDER=free" in text
    assert "FOOTBALL_DATA_SOURCE=free" in text
    assert "FOOTBALL_DATA_SEASON=2026" in text
    for league_id in ["kor.1", "kor.2", "jpn.1", "jpn.2", "aus.1", "bra.2", "arg.1", "usa.1", "mex.1", "uefa.europa.conf", "fifa.friendly"]:
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
    }
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


def test_docker_compose_allows_free_provider_leagues_env_override() -> None:
    text = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "DATA_PROVIDER: ${DATA_PROVIDER:-free}" in text
    assert "FOOTBALL_DATA_SOURCE: ${FOOTBALL_DATA_SOURCE:-free}" in text
    assert "FOOTBALL_DATA_SEASON: ${FOOTBALL_DATA_SEASON:-2026}" in text
    assert "FREE_PROVIDER_FOOTBALL_LEAGUES: ${FREE_PROVIDER_FOOTBALL_LEAGUES:-" in text
    for league_id in ["kor.1", "kor.2", "jpn.1", "jpn.2", "aus.1", "bra.2", "arg.2", "usa.1", "mex.2", "uefa.nations", "fifa.friendly"]:
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


def test_prediction_pipeline_runs_with_mock(mock_pipeline) -> None:
    results = mock_pipeline.run_today()
    assert len(results) == 1
    result = results[0]
    assert 0 <= result.hunter_score.score <= 100
    assert result.signal.signal.value in {"STRONG_BUY", "BUY", "WATCH", "PASS", "BLOCK"}


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


def test_api_health() -> None:
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["app"] == "SportsHunter-AI"


def test_recommendations_today_filters_pass_and_sorts_by_score() -> None:
    app.dependency_overrides[recommendations_router.get_prediction_pipeline] = lambda: _fake_recommendation_pipeline()
    try:
        client = TestClient(app)
        response = client.get("/api/recommendations/today")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert [item["signal"] for item in payload["items"]] == ["STRONG_BUY", "BUY"]
    assert [item["hunter_score"] for item in payload["items"]] == [91.0, 88.0]
    assert payload["items"][0]["stake"] == "2U"
    assert payload["items"][0]["odds"]["bookmaker"] == "DebugBook"


def test_recommendations_today_can_include_pass() -> None:
    app.dependency_overrides[recommendations_router.get_prediction_pipeline] = lambda: _fake_recommendation_pipeline()
    try:
        client = TestClient(app)
        response = client.get("/api/recommendations/today?include_pass=true")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 3
    assert [item["signal"] for item in payload["items"]] == ["STRONG_BUY", "BUY", "PASS"]


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
                    "league": "Debug League",
                    "match": "Debug Home vs Debug Away",
                    "kickoff": "2026-07-26T12:00:00+00:00",
                    "hunter_score": 91.0,
                    "confidence": 0.91,
                    "signal": "BUY",
                    "predicted_side": "Debug Home",
                    "stake": "2U",
                    "reason": "Debug reason",
                    "odds": {},
                }
            ],
        }
    )
    assert "Debug Home vs Debug Away" in message
    assert "信号: BUY" in message
    assert "仓位: 2U" in message


def test_telegram_test_api_sends_test_message(monkeypatch) -> None:
    sent_messages: list[str] = []

    class FakeNotifier:
        async def send_message(self, text: str) -> bool:
            sent_messages.append(text)
            return True

    monkeypatch.setattr(telegram_router, "TelegramNotifier", FakeNotifier)
    response = TestClient(app).post("/api/telegram/test")
    assert response.status_code == 200
    assert response.json() == {"success": True, "sent": True}
    assert sent_messages == ["SportsHunter AI 测试消息"]


def test_telegram_test_api_does_not_return_500_when_send_fails(monkeypatch) -> None:
    class FakeNotifier:
        async def send_message(self, text: str) -> bool:
            raise RuntimeError("telegram api failed")

    monkeypatch.setattr(telegram_router, "TelegramNotifier", FakeNotifier)
    response = TestClient(app).post("/api/telegram/test")
    assert response.status_code == 200
    assert response.json() == {"success": False, "sent": False}


def test_scheduler_registers_telegram_daily_job() -> None:
    scheduler = create_scheduler()
    assert "telegram_daily_recommendations" in {job.id for job in scheduler.get_jobs()}
    if scheduler.running:
        scheduler.shutdown(wait=False)


def test_telegram_daily_job_returns_push_result(monkeypatch) -> None:
    class FakePusher:
        async def push_today(self):
            return SimpleNamespace(to_dict=lambda: {"sent": True, "count": 1, "message": "ok"})

    monkeypatch.setattr(jobs, "RecommendationTelegramPusher", FakePusher)
    assert jobs.telegram_daily_recommendations() == {"sent": True, "count": 1, "message": "ok"}


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
    settings = Settings(data_provider="free", free_provider_football_leagues=["eng.1"], _env_file=None)
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
        free_provider_football_leagues=["eng.1", "esp.1", "ger.1", "esp.1"],
        _env_file=None,
    )
    provider = FreeFootballProvider(settings)
    provider.client = FakeJsonClient()
    fixtures = provider.get_today_fixtures()
    assert [fixture.id for fixture in fixtures] == ["800", "801"]
    assert {fixture.league.id for fixture in fixtures} == {"esp.1"}


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
            start_time=datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc),
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
                _fake_prediction_result(fixture("pass"), 77.0, "PASS", 0),
                _fake_prediction_result(fixture("strong"), 91.0, "STRONG_BUY", 2),
            ]

    return FakePipeline()


def _fake_prediction_result(fixture: Fixture, score: float, signal: str, stake: float):
    return SimpleNamespace(
        fixture=fixture,
        hunter_score=SimpleNamespace(score=score, confidence=0.91),
        signal=SimpleNamespace(signal=SimpleNamespace(value=signal), stake=stake, reason=f"{signal} reason"),
        predicted_side=fixture.home_team.name if stake else None,
    )
