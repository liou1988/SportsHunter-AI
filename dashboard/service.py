from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api.services.recommendations import build_today_recommendations
from config.settings import Settings, get_settings
from database.repositories import DashboardRepository
from database.session import SessionLocal
from datahub.hub import DataHub
from datahub.models import Fixture, Odds, OddsMarket, to_plain_dict
from evaluation.runner import EvaluationRunner
from pipeline.runner import PredictionPipeline
from telegram_bot.localization import (
    translate_fixture_status,
    translate_league_name,
    translate_match_text,
    translate_signal,
)

logger = logging.getLogger(__name__)


def build_dashboard_summary(
    datahub: DataHub,
    pipeline: PredictionPipeline | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    database = _database_status()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": _provider_status(datahub),
        "database": database,
        "recommendations": _archived_recommendation_status(database),
        "reports": _report_status(settings),
    }


def run_daily_evaluation(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    report = EvaluationRunner(reports_dir=settings.reports_dir).daily()
    return {
        "success": True,
        "report": {
            "period": report.period,
            "date": report.report_date.isoformat(),
            "settled_count": report.settled_count,
            "learning_records_created": report.learning_records_created,
            "wins": report.wins,
            "losses": report.losses,
            "module_notes": report.module_notes,
            "metrics": {
                "hunter_hit_rate": report.metrics.hunter_hit_rate,
                "signal_hit_rate": report.metrics.signal_hit_rate,
                "risk_effectiveness": report.metrics.risk_effectiveness,
                "confidence_calibration_error": report.metrics.confidence_calibration_error,
                "roi": report.metrics.roi,
                "by_league": report.metrics.by_league,
                "by_market": report.metrics.by_market,
            },
            "markdown": report.to_markdown(),
        },
    }


def check_data_quality(datahub: DataHub, max_odds_fixtures: int = 12) -> dict[str, Any]:
    started = time.perf_counter()
    checked_at = datetime.now(timezone.utc)
    provider = datahub.provider
    errors: list[dict[str, Any]] = []
    debug = _provider_debug_payload(datahub, errors)

    try:
        fixtures = datahub.get_today_fixtures()
    except Exception as exc:  # noqa: BLE001 - dashboard must return structured diagnostics
        logger.exception("dashboard data quality fixture scan failed", exc_info=exc)
        errors.append({"stage": "fixtures", "error": str(exc)})
        fixtures = []

    odds_sample = fixtures[: max(0, max_odds_fixtures)]
    odds_counts = {market.value: 0 for market in OddsMarket}
    fixtures_with_odds = 0
    sample_fixtures: list[dict[str, Any]] = []

    for fixture in odds_sample:
        odds_items = _fixture_odds(datahub, fixture, errors)
        markets = sorted({odds.market.value for odds in odds_items})
        if odds_items:
            fixtures_with_odds += 1
        for market in markets:
            odds_counts[market] = odds_counts.get(market, 0) + 1
        sample_fixtures.append(_quality_fixture_payload(fixture, markets))

    sample_size = len(odds_sample)
    provider_errors = debug.get("errors", [])
    has_errors = bool(errors or provider_errors)
    return {
        "provider": provider.name,
        "source": getattr(provider.settings, "football_data_source", "unknown"),
        "timezone": provider.settings.timezone,
        "checked_at": checked_at.isoformat(),
        "latency": round(time.perf_counter() - started, 3),
        "health": "warning" if has_errors else "ok",
        "today": debug.get("today") or checked_at.strftime("%Y%m%d"),
        "fixtures_count": len(fixtures),
        "leagues_count": len({fixture.league.id for fixture in fixtures}),
        "leagues_checked": debug.get("leagues_checked", []),
        "leagues_skipped": debug.get("leagues_skipped", []),
        "sources_checked": debug.get("sources_checked", [provider.name]),
        "fixtures_per_league": debug.get("fixtures_per_league", _fixtures_per_league(fixtures)),
        "fixtures_per_source": debug.get("fixtures_per_source", {}),
        "request_urls": debug.get("request_urls", [debug.get("request_url")] if debug.get("request_url") else []),
        "http_statuses": debug.get("http_statuses", {}),
        "fixtures_raw": debug.get("fixtures_raw", len(fixtures)),
        "fixtures_parsed": debug.get("fixtures_parsed", len(fixtures)),
        "odds_sample_size": sample_size,
        "fixtures_with_odds": fixtures_with_odds,
        "odds_market_counts": odds_counts,
        "odds_coverage": {
            market: {
                "fixtures": count,
                "ratio": round(count / sample_size, 4) if sample_size else 0.0,
            }
            for market, count in odds_counts.items()
        },
        "first_fixture": to_plain_dict(fixtures[0]) if fixtures else {},
        "sample_fixtures": sample_fixtures,
        "errors": [*provider_errors, *errors],
    }


def _provider_status(datahub: DataHub) -> dict[str, Any]:
    try:
        provider = datahub.provider
        health = provider.last_health or datahub.provider_status()
        if health is None:
            return {
                "provider": provider.name,
                "health": "unknown",
                "last_update": None,
                "latency": None,
                "error": "尚未执行数据源健康检查",
            }
        return {
            "provider": health.provider,
            "health": "ok" if health.health else "down",
            "last_update": health.last_update.isoformat(),
            "latency": health.latency,
            "error": health.error,
        }
    except Exception as exc:  # noqa: BLE001 - dashboard should render degraded status
        logger.exception("dashboard provider status failed", exc_info=exc)
        return {"provider": "unknown", "health": "down", "last_update": None, "latency": None, "error": str(exc)}


def _database_status() -> dict[str, Any]:
    try:
        with SessionLocal() as session:
            summary = DashboardRepository(session).summary()
        summary["latest_predictions"] = [_localize_prediction_item(item) for item in summary.get("latest_predictions", [])]
        return {"health": "ok", "error": None, **summary}
    except Exception as exc:  # noqa: BLE001 - fresh deployments may not have migrated yet
        logger.warning("dashboard database summary unavailable: %s", exc)
        return {
            "health": "not_ready",
            "error": str(exc),
            "counts": {},
            "latest_predictions": [],
        }


def _recommendation_status(pipeline: PredictionPipeline) -> dict[str, Any]:
    try:
        payload = build_today_recommendations(pipeline, include_pass=False)
        return {
            "health": "ok",
            "error": None,
            "count": payload["count"],
            "items": payload["items"][:8],
        }
    except Exception as exc:  # noqa: BLE001 - provider downtime should not break the shell
        logger.exception("dashboard recommendations failed", exc_info=exc)
        return {"health": "down", "error": str(exc), "count": 0, "items": []}


def _archived_recommendation_status(database: dict[str, Any]) -> dict[str, Any]:
    items = list(database.get("latest_predictions") or [])
    return {
        "health": "ok" if database.get("health") == "ok" else "unknown",
        "error": database.get("error"),
        "count": len(items),
        "items": [_localize_prediction_item(item) for item in items[:8]],
        "source": "predictions_archive",
    }


def _report_status(settings: Settings) -> dict[str, Any]:
    daily_path = settings.reports_dir / "daily_report.md"
    return {
        "daily_report": _file_payload(daily_path),
        "system_status": _file_payload(settings.system_status_path),
    }


def _file_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": str(path), "updated_at": None, "content": ""}
    try:
        stat = path.stat()
        return {
            "exists": True,
            "path": str(path),
            "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "content": path.read_text(encoding="utf-8")[:12000],
        }
    except OSError as exc:
        return {"exists": False, "path": str(path), "updated_at": None, "content": "", "error": str(exc)}


def _provider_debug_payload(datahub: DataHub, errors: list[dict[str, Any]]) -> dict[str, Any]:
    debug_today = getattr(datahub.provider, "debug_today", None)
    if not callable(debug_today):
        return {}
    try:
        payload = debug_today()
    except Exception as exc:  # noqa: BLE001 - quality endpoint should stay available
        logger.exception("dashboard provider debug failed", exc_info=exc)
        errors.append({"stage": "provider_debug", "error": str(exc)})
        return {}
    return payload if isinstance(payload, dict) else {}


def _fixture_odds(datahub: DataHub, fixture: Fixture, errors: list[dict[str, Any]]) -> list[Odds]:
    try:
        return datahub.get_odds(fixture.id)
    except Exception as exc:  # noqa: BLE001 - keep scanning other fixtures
        logger.warning("dashboard odds quality check failed", extra={"fixture_id": fixture.id}, exc_info=exc)
        errors.append(
            {
                "stage": "odds",
                "fixture_id": fixture.id,
                "match": f"{fixture.home_team.name} vs {fixture.away_team.name}",
                "error": str(exc),
            }
        )
        return []


def _quality_fixture_payload(fixture: Fixture, markets: list[str]) -> dict[str, Any]:
    return {
        "fixture_id": fixture.id,
        "league": translate_league_name(fixture.league.name),
        "match": translate_match_text(f"{fixture.home_team.name} vs {fixture.away_team.name}"),
        "kickoff": fixture.start_time.isoformat(),
        "status": fixture.status.value,
        "status_label": translate_fixture_status(fixture.status.value),
        "provider": fixture.provider,
        "odds_markets": markets,
    }


def _fixtures_per_league(fixtures: list[Fixture]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for fixture in fixtures:
        counts[fixture.league.id] = counts.get(fixture.league.id, 0) + 1
    return counts


def _localize_prediction_item(item: dict[str, Any]) -> dict[str, Any]:
    localized = dict(item)
    if localized.get("match"):
        localized["match"] = translate_match_text(str(localized["match"]))
    if localized.get("fixture"):
        localized["fixture"] = translate_match_text(str(localized["fixture"]))
    if localized.get("league"):
        localized["league"] = translate_league_name(str(localized["league"]))
    if localized.get("signal"):
        localized["signal_label"] = translate_signal(str(localized["signal"]))
    return localized
