from __future__ import annotations

from automation.health import SystemHealthCheck
from data_sync.engine import DataSync
from evaluation.runner import EvaluationRunner


def sync_today() -> dict:
    return DataSync().sync_today().__dict__


def update_odds() -> dict:
    return DataSync().update_odds().__dict__


def refresh_live() -> dict:
    return DataSync().sync_live().__dict__


def save_results() -> dict:
    return DataSync().sync_history().__dict__


def daily_report() -> str:
    return EvaluationRunner().daily().to_markdown()


def system_status() -> str:
    return str(SystemHealthCheck().write_status())
