from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies import get_datahub
from datahub.hub import DataHub
from datahub.models import to_plain_dict

router = APIRouter(prefix="/api/matches", tags=["matches"])


@router.get("/today")
def today_matches(datahub: DataHub = Depends(get_datahub)) -> dict:
    fixtures = datahub.get_today_fixtures()
    return {"count": len(fixtures), "items": to_plain_dict(fixtures)}


@router.get("/live")
def live_matches(datahub: DataHub = Depends(get_datahub)) -> dict:
    fixtures = datahub.get_live_matches()
    return {"count": len(fixtures), "items": to_plain_dict(fixtures)}
