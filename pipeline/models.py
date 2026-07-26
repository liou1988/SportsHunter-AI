from __future__ import annotations

from dataclasses import dataclass

from core.rating.engine import HunterScore
from core.risk.models import RiskResult
from core.signal.models import SignalResult
from datahub.models import Fixture, to_plain_dict
from features.models import FeatureVector


@dataclass(slots=True)
class PredictionResult:
    fixture: Fixture
    features: FeatureVector
    hunter_score: HunterScore
    risk: RiskResult
    signal: SignalResult
    predicted_side: str | None

    def to_dict(self) -> dict:
        return {
            "fixture": to_plain_dict(self.fixture),
            "features": self.features.to_dict(),
            "hunter_score": self.hunter_score.to_dict(),
            "risk": self.risk.to_dict(),
            "signal": self.signal.to_dict(),
            "predicted_side": self.predicted_side,
        }
