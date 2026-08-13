from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api.services.recommendations import build_archived_recommendations, build_today_recommendations
from config.settings import Settings, get_settings
from database.repositories import DashboardRepository
from database.session import SessionLocal
from datahub.hub import DataHub
from datahub.models import Fixture, Odds, OddsMarket, to_plain_dict
from evaluation.metrics import calculate_metrics
from evaluation.runner import EvaluationRunner
from optimizer.engine import ModelOptimizer
from pipeline.runner import PredictionPipeline
from telegram_bot.localization import (
    translate_fixture_status,
    translate_league_name,
    translate_match_text,
    translate_signal,
    translate_team_name,
)

logger = logging.getLogger(__name__)

STAT_PERIOD_OPTIONS = (3, 7, 15, 30)
DEFAULT_STAT_PERIOD_DAYS = 30


def build_dashboard_summary(
    datahub: DataHub,
    pipeline: PredictionPipeline | None = None,
    settings: Settings | None = None,
    period_days: int = DEFAULT_STAT_PERIOD_DAYS,
) -> dict[str, Any]:
    settings = settings or get_settings()
    period_days = _normalize_period_days(period_days)
    database = _database_status(period_days)
    recommendations = _archived_recommendation_status(database, settings)
    model_optimizer = _cached_model_optimizer_status(settings)
    reports = _report_status(settings, period_days)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period_days": period_days,
        "period_options": list(STAT_PERIOD_OPTIONS),
        "provider": _provider_status(datahub),
        "database": database,
        "recommendations": recommendations,
        "analytics": _analytics_status(
            database,
            period_days,
            model_optimizer=model_optimizer,
            reports=reports,
        ),
        "model_optimizer": model_optimizer,
        "reports": reports,
    }


def run_daily_evaluation(
    settings: Settings | None = None,
    period_days: int = DEFAULT_STAT_PERIOD_DAYS,
) -> dict[str, Any]:
    settings = settings or get_settings()
    period_days = _normalize_period_days(period_days)
    report = EvaluationRunner(reports_dir=settings.reports_dir).run_for_days(period_days)
    return {
        "success": True,
        "period_days": period_days,
        "period_options": list(STAT_PERIOD_OPTIONS),
        "report": {
            "period": report.period,
            "period_days": period_days,
            "date": report.report_date.isoformat(),
            "settled_count": report.settled_count,
            "learning_records_created": report.learning_records_created,
            "sample_breakdown": report.sample_breakdown,
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


def _cached_model_optimizer_status(settings: Settings) -> dict[str, Any]:
    path = settings.model_optimizer_status_path
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "status": "empty",
            "status_label": "待检查",
            "can_apply": False,
            "sample_count": 0,
            "min_recommended_sample": settings.model_optimizer_manual_min_samples,
            "wins": 0,
            "losses": 0,
            "hit_rate": 0.0,
            "roi": 0.0,
            "confidence_error": 0.0,
            "current_weights": {},
            "suggested_weights": {},
            "suggestions": [],
            "warnings": ["尚未生成模型优化状态，等待定时任务或手动检查。"],
        }
    report = payload.get("report") if isinstance(payload, dict) else None
    if isinstance(report, dict):
        return report
    return payload if isinstance(payload, dict) else {}


def apply_model_optimizer() -> dict[str, Any]:
    return ModelOptimizer().apply("monthly")


def _normalize_period_days(period_days: int | str | None) -> int:
    try:
        value = int(period_days or DEFAULT_STAT_PERIOD_DAYS)
    except (TypeError, ValueError):
        return DEFAULT_STAT_PERIOD_DAYS
    return value if value in STAT_PERIOD_OPTIONS else DEFAULT_STAT_PERIOD_DAYS


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
        health = provider.last_health
        if health is None:
            return {
                "provider": provider.name,
                "health": "unknown",
                "last_update": None,
                "latency": None,
                "error": "尚未执行数据源健康检查，可使用数据源质量检查刷新。",
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


def _database_status(period_days: int) -> dict[str, Any]:
    try:
        with SessionLocal() as session:
            summary = DashboardRepository(session).summary(days=period_days)
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
            "analytics": _empty_analytics(period_days),
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


def _archived_recommendation_status(database: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    if settings is not None:
        try:
            payload = build_archived_recommendations(
                include_pass=False,
                limit=80,
                alert_archive_path=settings.telegram_alert_archive_path,
            )
            items = _unique_dashboard_recommendations(
                [_localize_prediction_item(item) for item in list(payload.get("items") or [])]
            )
            return {
                "health": "ok" if database.get("health") == "ok" else "unknown",
                "error": payload.get("error"),
                "count": len(items),
                "items": items,
                "source": payload.get("source") or "telegram_alert_archive+predictions_archive",
            }
        except Exception as exc:  # noqa: BLE001 - dashboard can still fall back to DB summary
            logger.warning("dashboard archived recommendations unavailable: %s", exc)

    items = _unique_dashboard_recommendations(
        [_localize_prediction_item(item) for item in list(database.get("latest_predictions") or [])]
    )
    return {
        "health": "ok" if database.get("health") == "ok" else "unknown",
        "error": database.get("error"),
        "count": len(items),
        "items": items,
        "source": "predictions_archive_unique_latest",
    }


def _unique_dashboard_recommendations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = (
            str(item.get("league") or "").casefold().strip(),
            str(item.get("match") or item.get("fixture") or "").casefold().strip(),
            str(item.get("kickoff") or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _report_status(settings: Settings, period_days: int) -> dict[str, Any]:
    daily_path = settings.reports_dir / "daily_report.md"
    period_path = settings.reports_dir / f"last_{period_days}_days_report.md"
    period_payload = _file_payload(period_path)
    if not period_payload.get("exists"):
        period_payload = _file_payload(daily_path)
    return {
        "period_days": period_days,
        "evaluation_report": period_payload,
        "daily_report": _file_payload(daily_path),
        "system_status": _file_payload(settings.system_status_path),
    }


def _analytics_status(
    database: dict[str, Any],
    period_days: int,
    *,
    model_optimizer: dict[str, Any] | None = None,
    reports: dict[str, Any] | None = None,
) -> dict[str, Any]:
    analytics = {**_empty_analytics(period_days), **dict(database.get("analytics") or {})}
    analytics["period_days"] = period_days
    analytics["performance"] = _cached_performance_snapshot(
        period_days,
        model_optimizer=model_optimizer,
        reports=reports,
    )
    return analytics


def _cached_performance_snapshot(
    period_days: int,
    *,
    model_optimizer: dict[str, Any] | None = None,
    reports: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = _empty_performance(period_days)
    report_values = _performance_values_from_report(reports)
    if report_values:
        snapshot.update(report_values)
        snapshot["source"] = "cached_report"
        return snapshot

    optimizer_values = _performance_values_from_optimizer(model_optimizer)
    if optimizer_values:
        snapshot.update(optimizer_values)
        snapshot["source"] = "model_optimizer_cache"
        return snapshot

    snapshot["source"] = "empty"
    return snapshot


def _performance_values_from_report(reports: dict[str, Any] | None) -> dict[str, Any]:
    content = _report_content(reports)
    if not content:
        return {}

    settled_count = _parse_report_int(_report_line_value(content, "\u5df2\u7ed3\u7b97\u9884\u6d4b"))
    hunter_hit_rate = _parse_report_percent(_report_line_value(content, "Hunter \u8bc4\u5206\u547d\u4e2d\u7387"))
    signal_hit_rate = _parse_report_percent(_report_line_value(content, "\u4fe1\u53f7\u547d\u4e2d\u7387"))
    roi = _parse_report_percent(_report_line_value(content, "ROI"))
    calibration_error = _parse_report_float(_report_line_value(content, "\u4fe1\u5fc3\u6821\u51c6\u8bef\u5dee"))
    sample_breakdown = _parse_report_sample_breakdown(_report_line_value(content, "\u6837\u672c\u7ed3\u6784"))
    hit_rate = signal_hit_rate if signal_hit_rate is not None else hunter_hit_rate

    if settled_count is None and hit_rate is None and roi is None and calibration_error is None:
        return {}

    actionable_count = sample_breakdown.get("actionable_count") or settled_count or 0
    wins = round(actionable_count * hit_rate) if hit_rate is not None else 0
    losses = max(0, actionable_count - wins)
    return {
        "settled_count": settled_count or 0,
        "actionable_count": actionable_count,
        "sample_breakdown": sample_breakdown,
        "wins": wins,
        "losses": losses,
        "hit_rate": hit_rate or 0.0,
        "roi": roi or 0.0,
        "calibration_error": calibration_error or 0.0,
    }


def _performance_values_from_optimizer(model_optimizer: dict[str, Any] | None) -> dict[str, Any]:
    payload = _optimizer_report_payload(model_optimizer)
    if not payload:
        return {}

    sample_count = _coerce_int(payload.get("sample_count"))
    wins = _coerce_int(payload.get("wins"))
    losses = _coerce_int(payload.get("losses"))
    hit_rate = _coerce_float(payload.get("hit_rate"))
    roi = _coerce_float(payload.get("roi"))
    calibration_error = _coerce_float(payload.get("confidence_error"))
    if sample_count is None and wins is None and losses is None and hit_rate is None:
        return {}

    settled_count = sample_count or (wins or 0) + (losses or 0)
    return {
        "settled_count": settled_count,
        "actionable_count": settled_count,
        "wins": wins or 0,
        "losses": losses or 0,
        "hit_rate": hit_rate or 0.0,
        "roi": roi or 0.0,
        "calibration_error": calibration_error or 0.0,
    }


def _report_content(reports: dict[str, Any] | None) -> str:
    if not isinstance(reports, dict):
        return ""
    for key in ("evaluation_report", "daily_report"):
        payload = reports.get(key)
        if isinstance(payload, dict) and payload.get("content"):
            return str(payload.get("content") or "")
    return ""


def _optimizer_report_payload(model_optimizer: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(model_optimizer, dict):
        return {}
    if isinstance(model_optimizer.get("report"), dict):
        return dict(model_optimizer["report"])
    applied = model_optimizer.get("applied")
    if isinstance(applied, dict) and isinstance(applied.get("report"), dict):
        return dict(applied["report"])
    return dict(model_optimizer)


def _report_line_value(content: str, label: str) -> str | None:
    match = re.search(rf"^\s*-\s*{re.escape(label)}\s*[:\uff1a]\s*([^\n]+)", content, re.MULTILINE)
    return match.group(1).strip() if match else None


def _parse_report_int(value: str | None) -> int | None:
    number = _parse_report_float(value)
    return int(number) if number is not None else None


def _parse_report_percent(value: str | None) -> float | None:
    number = _parse_report_float(value)
    if number is None:
        return None
    return number / 100 if "%" in str(value) else number


def _parse_report_float(value: str | None) -> float | None:
    if value is None:
        return None
    match = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    return _coerce_float(match.group(0).replace(",", ""))


def _parse_report_sample_breakdown(value: str | None) -> dict[str, int]:
    if not value:
        return {}
    labels = {
        "total_count": "\u603b\u6837\u672c",
        "actionable_count": "\u53ef\u6267\u884c",
        "observation_count": "\u89c2\u5bdf/\u8df3\u8fc7",
        "block_count": "\u98ce\u63a7\u62e6\u622a",
    }
    breakdown: dict[str, int] = {}
    for key, label in labels.items():
        match = re.search(rf"{re.escape(label)}\s+(\d+)", value)
        if match:
            breakdown[key] = int(match.group(1))
    return breakdown


def _coerce_int(value: Any) -> int | None:
    number = _coerce_float(value)
    return int(number) if number is not None else None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _performance_snapshot(rows: list[dict[str, Any]], period_days: int) -> dict[str, Any]:
    metrics = calculate_metrics(rows)
    actionable_rows = [row for row in rows if row.get("actionable", True)]
    scored_rows = actionable_rows or rows
    wins = sum(1 for row in scored_rows if row.get("won"))
    losses = max(0, len(scored_rows) - wins)
    avg_confidence = _average([row.get("confidence") for row in scored_rows])
    avg_hunter_score = _average([row.get("hunter_score") for row in scored_rows])
    return {
        "period": f"last_{period_days}_days",
        "period_days": period_days,
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
        "odds_quality_performance": _odds_quality_performance(scored_rows),
        "clv_performance": _clv_performance(scored_rows),
        "odds_freshness_performance": _odds_freshness_performance(scored_rows),
        "module_errors": _module_errors(rows),
        "score_buckets": _settled_score_buckets(scored_rows),
        "confidence_bands": _confidence_bands(scored_rows),
    }


def _empty_performance(period_days: int = DEFAULT_STAT_PERIOD_DAYS) -> dict[str, Any]:
    return {
        "period": f"last_{period_days}_days",
        "period_days": period_days,
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
        "odds_quality_performance": [],
        "clv_performance": [],
        "odds_freshness_performance": [],
        "module_errors": [],
        "score_buckets": [],
        "confidence_bands": [],
    }


def _empty_analytics(period_days: int = DEFAULT_STAT_PERIOD_DAYS) -> dict[str, Any]:
    return {
        "period_days": period_days,
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


def _odds_quality_performance(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments = [
        ("closing_odds", "\u4e34\u573a\u76d8\u53e3", lambda row: bool(row.get("has_closing_odds"))),
        (
            "pre_match_odds",
            "\u666e\u901a\u76d8\u53e3",
            lambda row: int(row.get("odds_snapshot_count") or 0) > 0 and not row.get("has_closing_odds"),
        ),
        ("missing_odds", "\u65e0\u76d8\u53e3", lambda row: int(row.get("odds_snapshot_count") or 0) <= 0),
    ]
    items: list[dict[str, Any]] = []
    for segment, label, predicate in segments:
        segment_rows = [row for row in rows if predicate(row)]
        if not segment_rows:
            continue
        wins = sum(1 for row in segment_rows if row.get("won"))
        stake = sum(float(row.get("stake") or 0) for row in segment_rows) or 1.0
        profit = sum(float(row.get("profit") or 0) for row in segment_rows)
        items.append(
            {
                "segment": segment,
                "label": label,
                "count": len(segment_rows),
                "wins": wins,
                "hit_rate": wins / len(segment_rows) if segment_rows else 0.0,
                "roi": profit / stake,
                "avg_clv": _average_or_none([row.get("avg_clv") for row in segment_rows]),
                "trusted_clv": _average_or_none([row.get("trusted_clv") for row in segment_rows]),
                "sharp_anchor_count": sum(1 for row in segment_rows if row.get("has_sharp_anchor")),
            }
        )
    return items


def _clv_performance(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        clv_items = (row.get("clv") or {}).get("items") or []
        for item in clv_items:
            if item.get("clv") is None:
                continue
            grouped.setdefault(str(item.get("market") or "unknown"), []).append(item)

    items: list[dict[str, Any]] = []
    for market, market_items in grouped.items():
        clv_values = [float(item["clv"]) for item in market_items if item.get("clv") is not None]
        trusted_values = [
            float(item["clv"])
            for item in market_items
            if item.get("trusted") and item.get("clv") is not None
        ]
        positive_count = sum(1 for value in clv_values if value > 0)
        items.append(
            {
                "market": market,
                "label": _market_label(market),
                "count": len(clv_values),
                "positive_count": positive_count,
                "hit_rate": positive_count / len(clv_values) if clv_values else 0.0,
                "positive_rate": positive_count / len(clv_values) if clv_values else 0.0,
                "avg_clv": round(sum(clv_values) / len(clv_values), 4) if clv_values else None,
                "trusted_count": len(trusted_values),
                "trusted_avg_clv": round(sum(trusted_values) / len(trusted_values), 4) if trusted_values else None,
            }
        )
    return sorted(items, key=lambda item: (-int(item["count"]), str(item["market"])))


def _odds_freshness_performance(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = _group_rows(rows, "odds_freshness_bucket")
    order = {"0_30": 0, "31_90": 1, "91_360": 2, "stale": 3, "missing": 4, "unknown": 5}
    items: list[dict[str, Any]] = []
    for bucket, bucket_rows in grouped.items():
        wins = sum(1 for row in bucket_rows if row.get("won"))
        stake = sum(float(row.get("stake") or 0) for row in bucket_rows) or 1.0
        profit = sum(float(row.get("profit") or 0) for row in bucket_rows)
        items.append(
            {
                "bucket": bucket,
                "label": _odds_freshness_label(bucket),
                "count": len(bucket_rows),
                "wins": wins,
                "hit_rate": wins / len(bucket_rows) if bucket_rows else 0.0,
                "roi": profit / stake,
                "avg_clv": _average_or_none([row.get("avg_clv") for row in bucket_rows]),
                "sharp_anchor_count": sum(1 for row in bucket_rows if row.get("has_sharp_anchor")),
            }
        )
    return sorted(items, key=lambda item: (order.get(str(item["bucket"]), 99), -int(item["count"])))


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


def _average_or_none(values: list[Any]) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return None
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
    if localized.get("predicted_side"):
        localized["predicted_side"] = translate_team_name(str(localized["predicted_side"]))
    for key in ("market_prediction", "handicap"):
        if isinstance(localized.get(key), dict):
            localized[key] = _localize_market_payload(localized[key])
    if localized.get("signal"):
        localized["signal_label"] = translate_signal(str(localized["signal"]))
    if localized.get("fixture_status"):
        localized["status_label"] = translate_fixture_status(str(localized["fixture_status"]))
    return localized



def _localize_market_payload(payload: dict[str, Any]) -> dict[str, Any]:
    localized = dict(payload)
    if localized.get("predicted_side"):
        localized["predicted_side"] = translate_team_name(str(localized["predicted_side"]))
    handicap = localized.get("handicap")
    if isinstance(handicap, dict):
        localized["handicap"] = dict(handicap)
        if localized["handicap"].get("team"):
            localized["handicap"]["team"] = translate_team_name(str(localized["handicap"]["team"]))
    if localized.get("team"):
        localized["team"] = translate_team_name(str(localized["team"]))
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
        localized["predicted_side"] = translate_team_name(str(localized["predicted_side"]))
    localized["result_label"] = "命中" if localized.get("hit") else "未中"
    return localized


def _market_label(market: str) -> str:
    return {
        "moneyline": "\u80dc\u5e73\u8d1f",
        "totals": "\u5927\u5c0f\u7403",
        "handicap": "\u8ba9\u7403",
    }.get(str(market), str(market))


def _odds_freshness_label(bucket: str) -> str:
    return {
        "0_30": "0-30 \u5206\u949f",
        "31_90": "31-90 \u5206\u949f",
        "91_360": "91-360 \u5206\u949f",
        "stale": "\u8d85\u8fc7 6 \u5c0f\u65f6",
        "missing": "\u65e0\u76d8\u53e3",
        "unknown": "\u672a\u77e5",
    }.get(str(bucket), str(bucket))


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
