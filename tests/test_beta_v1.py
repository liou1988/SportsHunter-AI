from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.main import app
from config.settings import Settings
from database.base import Base
from database.models import OddsSnapshot
from database.repositories import SportsRepository
from datahub.providers.mock import MockProvider
from data_sync.models import SyncSummary
from core.risk.models import RiskBreakdown, RiskReason
from scheduler import jobs


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


def test_env_example_defaults_to_free_provider() -> None:
    text = Path(".env.example").read_text(encoding="utf-8")
    assert "DATA_PROVIDER=free" in text
    assert "FOOTBALL_DATA_SOURCE=free" in text
    assert "FOOTBALL_DATA_SEASON=2026" in text


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
