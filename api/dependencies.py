from __future__ import annotations

from datahub.hub import DataHub, build_datahub
from pipeline.runner import PredictionPipeline


def get_datahub() -> DataHub:
    return build_datahub()


def get_prediction_pipeline() -> PredictionPipeline:
    return PredictionPipeline()
