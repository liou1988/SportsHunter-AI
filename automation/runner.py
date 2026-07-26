from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from automation.health import SystemHealthCheck
from automation.schedule import AUTOMATION_JOBS
from config.settings import get_settings
from collector.history import HistoricalCollector
from data_sync.engine import DataSync
from evaluation.runner import EvaluationRunner
from telegram_bot.recommendations import RecommendationTelegramPusher

logger = logging.getLogger(__name__)


class AutomationRunner:
    def __init__(self, scheduler: BackgroundScheduler | None = None) -> None:
        settings = get_settings()
        self.scheduler = scheduler or BackgroundScheduler(timezone=settings.timezone)
        self.sync = DataSync()
        self.collector = HistoricalCollector(sync=self.sync)
        self.evaluation = EvaluationRunner()
        self.health = SystemHealthCheck()

    def register(self) -> BackgroundScheduler:
        self.scheduler.add_job(self.sync.sync_today, **AUTOMATION_JOBS["sync_today"], id="sync_today", replace_existing=True)
        self.scheduler.add_job(self.sync.update_odds, **AUTOMATION_JOBS["update_odds"], id="update_odds", replace_existing=True)
        self.scheduler.add_job(
            self._push_telegram_recommendations,
            **AUTOMATION_JOBS["telegram_daily_recommendations"],
            id="telegram_daily_recommendations",
            replace_existing=True,
        )
        self.scheduler.add_job(self.sync.sync_live, **AUTOMATION_JOBS["refresh_live"], id="refresh_live", replace_existing=True)
        self.scheduler.add_job(
            self.collector.collect_post_match,
            **AUTOMATION_JOBS["save_results"],
            id="save_results",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.evaluation.daily,
            **AUTOMATION_JOBS["daily_report"],
            id="daily_report",
            replace_existing=True,
        )
        self.scheduler.add_job(self.health.write_status, "interval", minutes=10, id="system_status", replace_existing=True)
        return self.scheduler

    def start(self) -> BackgroundScheduler:
        scheduler = self.register()
        if not scheduler.running:
            scheduler.start()
        logger.info("automation runner started")
        return scheduler

    @staticmethod
    def _push_telegram_recommendations() -> dict:
        return asyncio.run(RecommendationTelegramPusher().push_today()).to_dict()
