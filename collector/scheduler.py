from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from collector.history import HistoricalCollector


def register_collector_jobs(scheduler: BackgroundScheduler, collector: HistoricalCollector) -> None:
    scheduler.add_job(collector.collect_pre_match, "cron", hour=6, minute=0, id="collector_pre_match", replace_existing=True)
    scheduler.add_job(collector.collect_live, "interval", minutes=5, id="collector_live", replace_existing=True)
    scheduler.add_job(collector.collect_post_match, "cron", hour=23, minute=30, id="collector_post_match", replace_existing=True)
