from __future__ import annotations

from dataclasses import dataclass

from core.rating.engine import HunterRatingEngine
from core.risk.engine import RiskEngine
from core.signal.engine import SignalEngine
from datahub.hub import DataHub, build_datahub
from features.pipeline import FeatureBuilder, FeaturePipeline
from optimizer.weights import load_active_rating_weights
from pipeline.market_model import MarketPredictionModel


@dataclass(slots=True)
class PipelineContext:
    datahub: DataHub
    features: FeaturePipeline
    rating: HunterRatingEngine
    risk: RiskEngine
    signal: SignalEngine
    market: MarketPredictionModel


def build_pipeline_context(datahub: DataHub | None = None) -> PipelineContext:
    datahub = datahub or build_datahub()
    return PipelineContext(
        datahub=datahub,
        features=FeaturePipeline(FeatureBuilder(datahub)),
        rating=HunterRatingEngine(weights=load_active_rating_weights()),
        risk=RiskEngine(),
        signal=SignalEngine(),
        market=MarketPredictionModel(),
    )
