from __future__ import annotations

from dataclasses import dataclass

from core.rating.engine import HunterRatingEngine
from core.risk.engine import RiskEngine
from core.signal.engine import SignalEngine
from datahub.hub import DataHub, build_datahub
from features.pipeline import FeatureBuilder, FeaturePipeline


@dataclass(slots=True)
class PipelineContext:
    datahub: DataHub
    features: FeaturePipeline
    rating: HunterRatingEngine
    risk: RiskEngine
    signal: SignalEngine


def build_pipeline_context(datahub: DataHub | None = None) -> PipelineContext:
    datahub = datahub or build_datahub()
    return PipelineContext(
        datahub=datahub,
        features=FeaturePipeline(FeatureBuilder(datahub)),
        rating=HunterRatingEngine(),
        risk=RiskEngine(),
        signal=SignalEngine(),
    )
