from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response

from api.dependencies import get_prediction_pipeline
from api.services.recommendations import (
    build_archived_recommendations,
    build_recommendations_export_csv,
    build_today_recommendations,
)
from pipeline.runner import PredictionPipeline

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


@router.get("/today")
def recommendations_today(
    include_pass: bool = Query(False, description="Include PASS signals in the response."),
    pipeline: PredictionPipeline = Depends(get_prediction_pipeline),
) -> dict:
    return build_today_recommendations(pipeline, include_pass=include_pass)


@router.get("/archive")
def recommendations_archive(
    include_pass: bool = Query(False, description="Include PASS signals in the archive response."),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    return build_archived_recommendations(include_pass=include_pass, limit=limit)


@router.get("/export.csv")
def recommendations_export_csv(
    include_pass: bool = Query(False, description="Include PASS signals in the exported CSV."),
    limit: int = Query(200, ge=1, le=1000),
) -> Response:
    csv_body = build_recommendations_export_csv(include_pass=include_pass, limit=limit)
    filename = f"sportshunter_predictions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        content=csv_body,
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
