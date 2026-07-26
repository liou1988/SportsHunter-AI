from __future__ import annotations

from fastapi import APIRouter

from api.schemas import HealthResponse
from config.settings import get_settings

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(app=settings.app_name, status="ok", provider=settings.data_provider)
