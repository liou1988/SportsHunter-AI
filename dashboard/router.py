from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from api.dependencies import get_datahub
from dashboard.service import build_dashboard_summary, check_data_quality, run_daily_evaluation
from datahub.hub import DataHub

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="dashboard/templates")


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse(request, "index.html")


@router.get("/api/dashboard/summary")
def dashboard_summary(
    period_days: int = Query(30),
    datahub: DataHub = Depends(get_datahub),
) -> dict:
    return build_dashboard_summary(datahub, period_days=period_days)


@router.post("/api/dashboard/evaluation/run")
def dashboard_run_evaluation(period_days: int = Query(30)) -> dict:
    return run_daily_evaluation(period_days=period_days)


@router.post("/api/dashboard/data-quality/check")
def dashboard_data_quality_check(
    datahub: DataHub = Depends(get_datahub),
) -> dict:
    return check_data_quality(datahub)
