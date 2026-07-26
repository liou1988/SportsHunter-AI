from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)


class SchedulerWatchdog:
    def __init__(self, scheduler: BackgroundScheduler) -> None:
        self.scheduler = scheduler

    def ensure_running(self) -> bool:
        if self.scheduler.running:
            return True
        logger.warning("scheduler stopped; restarting")
        self.scheduler.start()
        return self.scheduler.running
