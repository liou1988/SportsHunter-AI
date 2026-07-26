from __future__ import annotations

from dataclasses import asdict
import asyncio

from automation.health import SystemHealthCheck
from data_sync.engine import DataSync
from evaluation.runner import EvaluationRunner
from telegram_bot.recommendations import RecommendationTelegramPusher


def sync_today() -> dict:
    return asdict(DataSync().sync_today())


def update_odds() -> dict:
    return asdict(DataSync().update_odds())


def refresh_live() -> dict:
    return asdict(DataSync().sync_live())


def save_results() -> dict:
    return asdict(DataSync().sync_history())


def daily_report() -> str:
    return EvaluationRunner().daily().to_markdown()


def telegram_daily_recommendations() -> dict:
    return asyncio.run(RecommendationTelegramPusher().push_today()).to_dict()


def system_status() -> str:
    return str(SystemHealthCheck().write_status())
