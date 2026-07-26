from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies import get_datahub
from datahub.hub import DataHub
from datahub.models import to_plain_dict

router = APIRouter(prefix="/api/scan", tags=["scan"])


@router.get("/today")
def scan_today(datahub: DataHub = Depends(get_datahub)) -> dict:
    fixtures = datahub.get_today_fixtures()
    return {"count": len(fixtures), "fixtures": to_plain_dict(fixtures)}
