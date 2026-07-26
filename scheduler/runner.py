from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from config.settings import get_settings
from scheduler import jobs


def create_scheduler() -> BackgroundScheduler:
    settings = get_settings()
    scheduler = BackgroundScheduler(timezone=settings.timezone)
    scheduler.add_job(jobs.sync_today, "cron", hour=6, minute=0, id="sync_today", replace_existing=True)
    scheduler.add_job(jobs.update_odds, "cron", hour=8, minute=0, id="update_odds", replace_existing=True)
    scheduler.add_job(jobs.refresh_live, "interval", minutes=5, id="refresh_live", replace_existing=True)
    scheduler.add_job(jobs.save_results, "cron", hour=23, minute=30, id="save_results", replace_existing=True)
    scheduler.add_job(jobs.daily_report, "cron", hour=1, minute=0, id="daily_report", replace_existing=True)
    scheduler.add_job(jobs.system_status, "interval", minutes=10, id="system_status", replace_existing=True)
    return scheduler
