from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api.services.recommendations import build_today_recommendations
from config.settings import Settings, get_settings
from database.repositories import DashboardRepository
from database.session import SessionLocal
from datahub.hub import DataHub
from evaluation.runner import EvaluationRunner
from pipeline.runner import PredictionPipeline

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
                "error": "尚未执行 Provider Health Check",
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
        "items": items[:8],
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
