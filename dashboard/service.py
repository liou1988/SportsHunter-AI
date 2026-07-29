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
from evaluation.dataset import EvaluationDataset
from evaluation.metrics import calculate_metrics
from evaluation.runner import EvaluationRunner
from optimizer.engine import ModelOptimizer
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
        "analytics": _analytics_status(database),
        "model_optimizer": model_optimizer_status(),
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
            "overview": report.overview,
            "wins": report.wins,
            "losses": report.losses,
            "confidence_notes": report.confidence_notes,
            "risk_notes": report.risk_notes,
            "module_contributions": report.module_contributions,
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


def model_optimizer_status() -> dict[str, Any]:
    return ModelOptimizer().build_report("monthly").to_dict()


def apply_model_optimizer() -> dict[str, Any]:
    return ModelOptimizer().apply("monthly")


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
        summary["analytics"] = _localize_analytics(summary.get("analytics", {}))
        return {"health": "ok", "error": None, **summary}
    except Exception as exc:  # noqa: BLE001 - fresh deployments may not have migrated yet
        logger.warning("dashboard database summary unavailable: %s", exc)
        return {
            "health": "not_ready",
            "error": str(exc),
            "counts": {},
            "latest_predictions": [],
            "analytics": _empty_analytics(),
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
    counts = database.get("counts") or {}
    return {
        "health": "ok" if database.get("health") == "ok" else "unknown",
        "error": database.get("error"),
        "count": counts.get("predictions", len(items)),
        "items": [_localize_prediction_item(item) for item in items[:8]],
        "source": "predictions_archive",
    }


def _report_status(settings: Settings) -> dict[str, Any]:
    daily_path = settings.reports_dir / "daily_report.md"
    return {
        "daily_report": _file_payload(daily_path),
        "system_status": _file_payload(settings.system_status_path),
    }


def _analytics_status(database: dict[str, Any]) -> dict[str, Any]:
    analytics = {**_empty_analytics(), **dict(database.get("analytics") or {})}
    try:
        rows = EvaluationDataset().rows("monthly")
        analytics["performance"] = _performance_snapshot(rows)
    except Exception as exc:  # noqa: BLE001 - dashboard can still show operational status
        logger.warning("dashboard performance analytics unavailable: %s", exc)
        analytics["performance"] = _empty_performance()
        analytics["error"] = str(exc)
    return analytics


def _localize_analytics(analytics: dict[str, Any]) -> dict[str, Any]:
    localized = dict(analytics or {})
    localized["signal_distribution"] = [
        {**item, "signal_label": translate_signal(str(item.get("signal") or ""))}
        for item in localized.get("signal_distribution", [])
    ]
    localized["league_activity"] = [
        {**item, "league": translate_league_name(str(item.get("league") or ""))}
        for item in localized.get("league_activity", [])
    ]
    localized["risk_distribution"] = [
        {**item, "risk_label": _risk_label(str(item.get("risk_level") or ""))}
        for item in localized.get("risk_distribution", [])
    ]
    localized["latest_settled"] = [
        _localize_settled_item(item)
        for item in localized.get("latest_settled", [])
    ]
    return localized


def _performance_snapshot(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = calculate_metrics(rows)
    actionable_rows = [row for row in rows if row.get("actionable", True)]
    scored_rows = actionable_rows or rows
    wins = sum(1 for row in scored_rows if row.get("won"))
    losses = max(0, len(scored_rows) - wins)
    avg_confidence = _average([row.get("confidence") for row in scored_rows])
    avg_hunter_score = _average([row.get("hunter_score") for row in scored_rows])
    return {
        "period": "monthly",
        "settled_count": len(rows),
        "actionable_count": len(actionable_rows),
        "wins": wins,
        "losses": losses,
        "hit_rate": metrics.signal_hit_rate,
        "roi": metrics.roi,
        "avg_confidence": avg_confidence,
        "avg_hunter_score": avg_hunter_score,
        "calibration_error": metrics.confidence_calibration_error,
        "league_performance": _league_performance(scored_rows),
        "market_performance": _market_performance(rows),
        "module_errors": _module_errors(rows),
        "score_buckets": _settled_score_buckets(scored_rows),
        "confidence_bands": _confidence_bands(scored_rows),
    }


def _empty_performance() -> dict[str, Any]:
    return {
        "period": "monthly",
        "settled_count": 0,
        "actionable_count": 0,
        "wins": 0,
        "losses": 0,
        "hit_rate": 0.0,
        "roi": 0.0,
        "avg_confidence": 0.0,
        "avg_hunter_score": 0.0,
        "calibration_error": 0.0,
        "league_performance": [],
        "market_performance": [],
        "module_errors": [],
        "score_buckets": [],
        "confidence_bands": [],
    }


def _empty_analytics() -> dict[str, Any]:
    return {
        "period_days": 30,
        "prediction_trend": [],
        "signal_distribution": [],
        "risk_distribution": [],
        "score_buckets": [],
        "league_activity": [],
        "latest_settled": [],
    }


def _league_performance(rows: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    grouped = _group_rows(rows, "league")
    items = []
    for league, league_rows in grouped.items():
        wins = sum(1 for row in league_rows if row.get("won"))
        stake = sum(float(row.get("stake") or 0) for row in league_rows) or 1.0
        profit = sum(float(row.get("profit") or 0) for row in league_rows)
        items.append(
            {
                "league": translate_league_name(league),
                "count": len(league_rows),
                "wins": wins,
                "losses": len(league_rows) - wins,
                "hit_rate": wins / len(league_rows) if league_rows else 0.0,
                "roi": profit / stake,
                "avg_score": _average([row.get("hunter_score") for row in league_rows]),
            }
        )
    return sorted(items, key=lambda item: (-int(item["count"]), -float(item["hit_rate"]), str(item["league"])))[:limit]


def _market_performance(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    markets = [
        ("moneyline", "胜平负"),
        ("totals", "大小球"),
        ("handicap", "让球"),
    ]
    items = []
    for market, label in markets:
        hits = []
        for row in rows:
            value = (row.get("market_results") or {}).get(market)
            if value is not None:
                hits.append(bool(value))
        wins = sum(1 for value in hits if value)
        items.append(
            {
                "market": market,
                "label": label,
                "count": len(hits),
                "wins": wins,
                "hit_rate": wins / len(hits) if hits else 0.0,
            }
        )
    return items


def _module_errors(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    losses = [row for row in rows if row.get("actionable", True) and not row.get("won")]
    grouped = _group_rows(losses, "primary_error_module")
    items = [
        {
            "module": module,
            "label": _module_label(module),
            "count": len(module_rows),
            "avg_score_error": _average([row.get("score_error") for row in module_rows]),
        }
        for module, module_rows in grouped.items()
    ]
    return sorted(items, key=lambda item: (-int(item["count"]), str(item["label"])))


def _settled_score_buckets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets = [
        ("90+", 90.0, 101.0),
        ("85-89", 85.0, 90.0),
        ("80-84", 80.0, 85.0),
        ("60-79", 60.0, 80.0),
        ("60以下", 0.0, 60.0),
    ]
    items = []
    for label, floor, ceiling in buckets:
        bucket_rows = [
            row
            for row in rows
            if row.get("hunter_score") is not None and floor <= float(row["hunter_score"]) < ceiling
        ]
        wins = sum(1 for row in bucket_rows if row.get("won"))
        items.append(
            {
                "bucket": label,
                "count": len(bucket_rows),
                "wins": wins,
                "hit_rate": wins / len(bucket_rows) if bucket_rows else 0.0,
            }
        )
    return items


def _confidence_bands(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bands = [
        ("0.85+", 0.85, 1.01),
        ("0.70-0.84", 0.70, 0.85),
        ("0.50-0.69", 0.50, 0.70),
        ("0.50以下", 0.0, 0.50),
    ]
    items = []
    for label, floor, ceiling in bands:
        band_rows = [
            row
            for row in rows
            if row.get("confidence") is not None and floor <= float(row["confidence"]) < ceiling
        ]
        wins = sum(1 for row in band_rows if row.get("won"))
        items.append(
            {
                "band": label,
                "count": len(band_rows),
                "wins": wins,
                "hit_rate": wins / len(band_rows) if band_rows else 0.0,
            }
        )
    return items


def _group_rows(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(key) or "unknown"), []).append(row)
    return grouped


def _average(values: list[Any]) -> float:
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return 0.0
    return round(sum(numbers) / len(numbers), 4)


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


def _localize_settled_item(item: dict[str, Any]) -> dict[str, Any]:
    localized = dict(item)
    if localized.get("fixture"):
        localized["fixture"] = translate_match_text(str(localized["fixture"]))
    if localized.get("league"):
        localized["league"] = translate_league_name(str(localized["league"]))
    if localized.get("signal"):
        localized["signal_label"] = translate_signal(str(localized["signal"]))
    if localized.get("predicted_side"):
        localized["predicted_side"] = translate_match_text(str(localized["predicted_side"]))
    localized["result_label"] = "命中" if localized.get("hit") else "未中"
    return localized


def _module_label(module: str) -> str:
    return {
        "aligned_signal": "信号一致性",
        "score_projection": "比分预测",
        "totals_market": "大小球盘口",
        "handicap_market": "让球盘口",
        "signal": "最终信号",
        "unknown": "未知模块",
        "team_strength": "球队实力",
        "recent_form": "近期状态",
        "attack": "进攻指数",
        "defense": "防守指数",
        "home_advantage": "主场优势",
        "odds_movement": "赔率变化",
        "market_heat": "市场热度",
        "league_strength": "联赛强度",
        "fatigue": "体能疲劳",
        "injury": "伤停风险",
        "live_momentum": "滚球动能",
    }.get(str(module), str(module))


def _risk_label(risk_level: str) -> str:
    return {
        "LOW": "低风险",
        "MEDIUM": "中风险",
        "HIGH": "高风险",
        "BLOCK": "风控拦截",
        "UNKNOWN": "未知",
    }.get(str(risk_level), str(risk_level))
