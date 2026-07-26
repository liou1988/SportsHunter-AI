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
