from __future__ import annotations

from functools import lru_cache

from datahub.hub import DataHub, build_datahub
from pipeline.context import build_pipeline_context
from pipeline.runner import PredictionPipeline


@lru_cache(maxsize=1)
def get_datahub() -> DataHub:
    return build_datahub()


def get_prediction_pipeline() -> PredictionPipeline:
    return PredictionPipeline(build_pipeline_context(get_datahub()))
