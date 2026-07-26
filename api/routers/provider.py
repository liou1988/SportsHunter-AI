from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies import get_datahub
from api.schemas import ProviderStatusResponse
from datahub.hub import DataHub

router = APIRouter(tags=["provider"])


@router.get("/provider/status", response_model=ProviderStatusResponse)
def provider_status(datahub: DataHub = Depends(get_datahub)) -> ProviderStatusResponse:
    health = datahub.provider_status()
    return ProviderStatusResponse(
        provider=health.provider,
        health=health.health,
        last_update=health.last_update.isoformat(),
        latency=health.latency,
        error=health.error,
    )


@router.get("/api/provider/debug")
def provider_debug(datahub: DataHub = Depends(get_datahub)) -> dict:
    debug_today = getattr(datahub.provider, "debug_today", None)
    if callable(debug_today):
        return debug_today()

    return {
        "provider": datahub.provider.name,
        "source": getattr(datahub.provider.settings, "football_data_source", "unknown"),
        "timezone": datahub.provider.settings.timezone,
        "today": "",
        "request_url": "",
        "http_status": None,
        "fixtures_raw": 0,
        "fixtures_parsed": 0,
        "first_fixture": {},
        "errors": ["provider does not expose debug_today"],
    }
