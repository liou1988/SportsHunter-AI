from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from config.settings import get_settings
from scheduler import jobs


def create_scheduler() -> BackgroundScheduler:
    settings = get_settings()
    scheduler = BackgroundScheduler(timezone=settings.timezone)
    scheduler.add_job(jobs.sync_today, "cron", hour=6, minute=0, id="sync_today", replace_existing=True)
    scheduler.add_job(jobs.update_odds, "cron", hour=8, minute=0, id="update_odds", replace_existing=True)
    scheduler.add_job(
        jobs.archive_today_predictions,
        "cron",
        hour=8,
        minute=10,
        id="archive_today_predictions",
        replace_existing=True,
    )
    scheduler.add_job(
        jobs.telegram_recommendation_alerts,
        "interval",
        minutes=max(1, settings.telegram_alert_interval_minutes),
        id="telegram_recommendation_alerts",
        replace_existing=True,
    )
    scheduler.add_job(jobs.refresh_live, "interval", minutes=5, id="refresh_live", replace_existing=True)
    scheduler.add_job(jobs.save_results, "interval", minutes=30, id="save_results", replace_existing=True)
    scheduler.add_job(jobs.daily_report, "cron", hour=10, minute=0, id="daily_report", replace_existing=True)
    if settings.model_optimizer_enabled:
        scheduler.add_job(
            jobs.model_optimizer_check,
            "cron",
            hour=settings.model_optimizer_check_hour,
            minute=settings.model_optimizer_check_minute,
            id="model_optimizer_check",
            replace_existing=True,
        )
    scheduler.add_job(jobs.system_status, "interval", minutes=10, id="system_status", replace_existing=True)
    return scheduler
