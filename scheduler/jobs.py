from __future__ import annotations

from dataclasses import asdict
import asyncio

from automation.health import SystemHealthCheck
from collector.history import HistoricalCollector
from data_sync.engine import DataSync
from evaluation.runner import EvaluationRunner
from optimizer.scheduler import run_scheduled_optimizer_check
from telegram_bot.alerts import RecommendationAlertPusher


def sync_today() -> dict:
    return asdict(DataSync().sync_today())


def update_odds() -> dict:
    return asdict(DataSync().update_odds())


def refresh_live() -> dict:
    return asdict(DataSync().sync_live())


def save_results() -> dict:
    return asdict(HistoricalCollector().collect_post_match())


def daily_report() -> str:
    return EvaluationRunner().daily().to_markdown()


def model_optimizer_check() -> dict:
    return run_scheduled_optimizer_check()


def telegram_recommendation_alerts() -> dict:
    return asyncio.run(RecommendationAlertPusher().push_new()).to_dict()


def system_status() -> str:
    return str(SystemHealthCheck().write_status())
