from __future__ import annotations

from datetime import datetime

from pipeline.context import PipelineContext, build_pipeline_context
from pipeline.filters import prediction_candidate_fixtures
from pipeline.models import PredictionResult


class PredictionPipeline:
    def __init__(self, context: PipelineContext | None = None) -> None:
        self.context = context or build_pipeline_context()

    def run_today(self, now: datetime | None = None) -> list[PredictionResult]:
        today_fixtures = self.context.datahub.get_today_fixtures()
        try:
            live_fixtures = self.context.datahub.get_live_matches()
        except Exception:  # noqa: BLE001 - today predictions should survive live-feed outages
            live_fixtures = []
        fixtures = prediction_candidate_fixtures(today_fixtures, live_fixtures, now=now)
        return [self.run_fixture(fixture.id) for fixture in fixtures]

    def run_fixture(self, fixture_id: str) -> PredictionResult:
        fixture = self.context.datahub.get_fixture(fixture_id)
        features = self.context.features.build(fixture_id)
        hunter_score = self.context.rating.score(features)
        risk = self.context.risk.evaluate(features)
        signal = self.context.signal.generate(hunter_score, risk, features)
        try:
            odds = self.context.datahub.get_odds(fixture_id)
        except Exception:  # noqa: BLE001 - market model can work from features only
            odds = []
        market_prediction = self.context.market.predict(fixture, features, odds)
        predicted_side = market_prediction.predicted_side if signal.stake > 0 else None
        return PredictionResult(
            fixture=fixture,
            features=features,
            hunter_score=hunter_score,
            risk=risk,
            signal=signal,
            market_prediction=market_prediction,
            predicted_side=predicted_side,
        )

    def run_live(self, fixture_id: str) -> PredictionResult:
        return self.run_fixture(fixture_id)
