from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.routers import datahub, health, matches, model, predictions, provider, recommendations, scan, telegram
from config.logging import configure_logging
from config.settings import get_settings
from dashboard.router import router as dashboard_router
from scheduler.runner import create_scheduler

configure_logging()
logger = logging.getLogger(__name__)
settings = get_settings()
_scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _scheduler
    if settings.enable_scheduler and settings.automation_enabled:
        _scheduler = create_scheduler()
        _scheduler.start()
        logger.info("scheduler started")
    yield
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("scheduler stopped")


app = FastAPI(
    title=settings.app_name,
    version="1.0.1-beta.1",
    description="SportsHunter-AI professional sports prediction API.",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(provider.router)
app.include_router(scan.router)
app.include_router(matches.router)
app.include_router(model.router)
app.include_router(predictions.router)
app.include_router(recommendations.router)
app.include_router(datahub.router)
app.include_router(telegram.router)
app.include_router(dashboard_router)
app.mount("/dashboard/static", StaticFiles(directory="dashboard/static"), name="dashboard_static")
