from __future__ import annotations

from fastapi import APIRouter

from dashboard.service import apply_model_optimizer, model_optimizer_status

router = APIRouter(tags=["model"])


@router.get("/api/model/optimizer/suggestions")
def model_optimizer_suggestions() -> dict:
    return model_optimizer_status()


@router.post("/api/model/optimizer/apply")
def model_optimizer_apply() -> dict:
    return apply_model_optimizer()
