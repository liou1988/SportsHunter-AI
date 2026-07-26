AUTOMATION_JOBS = {
    "sync_today": {"trigger": "cron", "hour": 6, "minute": 0},
    "update_odds": {"trigger": "cron", "hour": 8, "minute": 0},
    "telegram_daily_recommendations": {"trigger": "cron", "hour": 8, "minute": 0},
    "refresh_live": {"trigger": "interval", "minutes": 5},
    "save_results": {"trigger": "cron", "hour": 23, "minute": 30},
    "daily_report": {"trigger": "cron", "hour": 1, "minute": 0},
}
