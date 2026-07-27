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
from database.models import LearningRecord, MatchResult, OddsSnapshot, Prediction
from database.repositories import SportsRepository
from datahub.hub import DataHub
from datahub.models import Fixture, FixtureStatus, League, Odds, OddsMarket, Score, Team
from datahub.providers.mock import MockProvider
from data_sync.models import SyncSummary
from core.risk.models import RiskBreakdown, RiskLevel, RiskReason
from core.signal.models import Signal
from core.signal.rules import decide_signal
from core.signal.strategy import SIGNAL_STRATEGY
from evaluation.dataset import EvaluationDataset
from evaluation.runner import EvaluationRunner
from evaluation.settlement import SettlementService
from pipeline.archive import PredictionArchive
from pipeline.models import HandicapPrediction, MarketPrediction, ScorePrediction, TotalGoalsPrediction
from free_provider.football import FreeFootballProvider, LEAGUE_NAMES
from api import dependencies
from api.routers import provider as provider_router
from api.routers import recommendations as recommendations_router
from api.routers import telegram as telegram_router
from dashboard.router import get_datahub as dashboard_get_datahub
from scheduler import jobs
from scheduler.runner import create_scheduler
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


def test_settings_parse_free_provider_sources(monkeypatch) -> None:
    monkeypatch.setenv("FREE_PROVIDER_SOURCES", "espn,thesportsdb")
    settings = Settings(_env_file=None)
    assert settings.free_provider_sources == ["espn", "thesportsdb"]


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


def test_env_example_contains_triggered_alert_settings() -> None:
    text = Path(".env.example").read_text(encoding="utf-8")
    assert "TELEGRAM_ALERT_SIGNALS=STRONG_BUY,BUY,WATCH" in text
    assert "TELEGRAM_ALERT_INTERVAL_MINUTES=5" in text
    assert "TELEGRAM_ALERT_RETENTION_DAYS=7" in text
    assert "TELEGRAM_ALERT_ARCHIVE_PATH=reports/telegram_alerts.json" in text


def test_docker_compose_allows_free_provider_leagues_env_override() -> None:
    text = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "DATA_PROVIDER: ${DATA_PROVIDER:-free}" in text
    assert "FOOTBALL_DATA_SOURCE: ${FOOTBALL_DATA_SOURCE:-free}" in text
    assert "FOOTBALL_DATA_SEASON: ${FOOTBALL_DATA_SEASON:-2026}" in text
    assert "FREE_PROVIDER_SOURCES: ${FREE_PROVIDER_SOURCES:-espn,thesportsdb}" in text
    assert "FREE_PROVIDER_THESPORTSDB_BASE_URL: ${FREE_PROVIDER_THESPORTSDB_BASE_URL:-https://www.thesportsdb.com/api/v1/json/3}" in text
    assert "FREE_PROVIDER_FOOTBALL_LEAGUES: ${FREE_PROVIDER_FOOTBALL_LEAGUES:-" in text
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
    assert "## Why Wins" in report.to_markdown()
    assert "## Why Losses" in report.to_markdown()
    assert (tmp_path / "daily_report.md").exists()


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
    assert "预测运行、推荐归档和自动复盘控制台" in response.text


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
    assert payload["recommendations"]["source"] == "predictions_archive"
    assert "database" in payload
    assert "reports" in payload


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
    assert "戈亚尼亚竞技 对阵 欧帕瑞欧PR" in message
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
    assert translate_team_name("Operário PR") == "欧帕瑞欧PR"
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
    assert "戈亚尼亚竞技 对阵 欧帕瑞欧PR" in message
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
    )

    first = asyncio.run(pusher.push_new())
    second = asyncio.run(pusher.push_new())

    assert first.success is True
    assert first.sent is True
    assert first.evaluated_count == 4
    assert first.eligible_count == 3
    assert first.pushed_count == 3
    assert second.success is True
    assert second.sent is False
    assert second.pushed_count == 0
    assert second.skipped_count == 3
    assert len(sent_messages) == 3
    assert all("SportsHunter AI 发现合适比赛" in message for message in sent_messages)


def test_telegram_alert_message_formats_single_prediction() -> None:
    pipeline = _fake_recommendation_pipeline()
    result = pipeline.run_today()[0]
    message = format_recommendation_alert_message(pipeline, result)
    assert "SportsHunter AI 发现合适比赛" in message
    assert "信号：推荐" in message
    assert "仓位：1.5U" in message
    assert "比分预测：2-1" in message
    assert "大小球：大 2.5" in message
    assert "让球：Debug Home -0.25" in message
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
    assert payload["pushed_count"] == 3
    assert len(sent_messages) == 3


def test_scheduler_registers_triggered_telegram_alert_job() -> None:
    scheduler = create_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert "telegram_recommendation_alerts" in job_ids
    assert "telegram_daily_recommendations" not in job_ids
    if scheduler.running:
        scheduler.shutdown(wait=False)


def test_telegram_alert_job_returns_push_result(monkeypatch) -> None:
    class FakePusher:
        async def push_new(self):
            return SimpleNamespace(to_dict=lambda: {"sent": True, "pushed_count": 1, "message": "ok"})

    monkeypatch.setattr(jobs, "RecommendationAlertPusher", FakePusher)
    assert jobs.telegram_recommendation_alerts() == {"sent": True, "pushed_count": 1, "message": "ok"}


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
