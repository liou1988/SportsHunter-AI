from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.dependencies import get_prediction_pipeline
from api.services.recommendations import build_today_recommendations
from pipeline.runner import PredictionPipeline

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


@router.get("/today")
def recommendations_today(
    include_pass: bool = Query(False, description="Include PASS signals in the response."),
    pipeline: PredictionPipeline = Depends(get_prediction_pipeline),
) -> dict:
    return build_today_recommendations(pipeline, include_pass=include_pass)
