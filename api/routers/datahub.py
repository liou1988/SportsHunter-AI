from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies import get_datahub
from datahub.hub import DataHub
from datahub.models import to_plain_dict

router = APIRouter(prefix="/api/datahub", tags=["datahub"])


@router.get("/standings/{league}")
def standings(league: str, datahub: DataHub = Depends(get_datahub)) -> dict:
    items = datahub.get_standings(league)
    return {"count": len(items), "items": to_plain_dict(items)}
