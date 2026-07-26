from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies import get_prediction_pipeline
from pipeline.runner import PredictionPipeline

router = APIRouter(prefix="/api/predictions", tags=["predictions"])


@router.get("/today")
def predictions_today(pipeline: PredictionPipeline = Depends(get_prediction_pipeline)) -> dict:
    results = pipeline.run_today()
    return {"count": len(results), "items": [result.to_dict() for result in results]}


@router.get("/{fixture_id}")
def prediction_fixture(fixture_id: str, pipeline: PredictionPipeline = Depends(get_prediction_pipeline)) -> dict:
    return pipeline.run_fixture(fixture_id).to_dict()
