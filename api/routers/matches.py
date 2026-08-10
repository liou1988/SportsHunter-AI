from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies import get_datahub
from datahub.hub import DataHub
from datahub.models import to_plain_dict
from pipeline.filters import prediction_candidate_fixtures

router = APIRouter(prefix="/api/matches", tags=["matches"])


@router.get("/today")
def today_matches(datahub: DataHub = Depends(get_datahub)) -> dict:
    source_fixtures = datahub.get_today_fixtures()
    try:
        live_fixtures = datahub.get_live_matches()
    except Exception:  # noqa: BLE001 - matches view should still show scheduled candidates
        live_fixtures = []
    fixtures = prediction_candidate_fixtures(source_fixtures, live_fixtures)
    return {
        "count": len(fixtures),
        "source_count": len(source_fixtures),
        "live_count": len(live_fixtures),
        "items": to_plain_dict(fixtures),
    }


@router.get("/live")
def live_matches(datahub: DataHub = Depends(get_datahub)) -> dict:
    fixtures = datahub.get_live_matches()
    return {"count": len(fixtures), "items": to_plain_dict(fixtures)}
