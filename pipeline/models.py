from __future__ import annotations

from dataclasses import dataclass

from core.rating.engine import HunterScore
from core.risk.models import RiskResult
from core.signal.models import SignalResult
from datahub.models import Fixture, to_plain_dict
from features.models import FeatureVector


@dataclass(slots=True)
class ScorePrediction:
    home: int
    away: int
    expected_home_goals: float
    expected_away_goals: float
    text: str

    def to_dict(self) -> dict:
        return {
            "home": self.home,
            "away": self.away,
            "expected_home_goals": self.expected_home_goals,
            "expected_away_goals": self.expected_away_goals,
            "text": self.text,
        }


@dataclass(slots=True)
class TotalGoalsPrediction:
    line: float
    pick: str
    label: str
    expected_total: float
    confidence: float
    reason: str
    edge: float = 0.0
    bookmaker: str | None = None
    over_odds: float | None = None
    under_odds: float | None = None
    market_available: bool = False

    def to_dict(self) -> dict:
        return {
            "line": self.line,
            "pick": self.pick,
            "label": self.label,
            "expected_total": self.expected_total,
            "confidence": self.confidence,
            "reason": self.reason,
            "edge": self.edge,
            "bookmaker": self.bookmaker,
            "over_odds": self.over_odds,
            "under_odds": self.under_odds,
            "market_available": self.market_available,
        }


@dataclass(slots=True)
class HandicapPrediction:
    side: str | None
    team: str | None
    line: float
    pick: str
    label: str
    expected_margin: float
    confidence: float
    reason: str
    edge: float = 0.0
    bookmaker: str | None = None
    home_odds: float | None = None
    away_odds: float | None = None
    market_available: bool = False

    def to_dict(self) -> dict:
        return {
            "side": self.side,
            "team": self.team,
            "line": self.line,
            "pick": self.pick,
            "label": self.label,
            "expected_margin": self.expected_margin,
            "confidence": self.confidence,
            "reason": self.reason,
            "edge": self.edge,
            "bookmaker": self.bookmaker,
            "home_odds": self.home_odds,
            "away_odds": self.away_odds,
            "market_available": self.market_available,
        }


@dataclass(slots=True)
class MarketPrediction:
    predicted_side: str | None
    moneyline_pick: str
    score: ScorePrediction
    total_goals: TotalGoalsPrediction
    handicap: HandicapPrediction
    notes: list[str]

    def to_dict(self) -> dict:
        return {
            "predicted_side": self.predicted_side,
            "moneyline_pick": self.moneyline_pick,
            "score": self.score.to_dict(),
            "total_goals": self.total_goals.to_dict(),
            "handicap": self.handicap.to_dict(),
            "notes": self.notes,
        }


@dataclass(slots=True)
class PredictionResult:
    fixture: Fixture
    features: FeatureVector
    hunter_score: HunterScore
    risk: RiskResult
    signal: SignalResult
    market_prediction: MarketPrediction
    predicted_side: str | None

    def to_dict(self) -> dict:
        return {
            "fixture": to_plain_dict(self.fixture),
            "features": self.features.to_dict(),
            "hunter_score": self.hunter_score.to_dict(),
            "risk": self.risk.to_dict(),
            "signal": self.signal.to_dict(),
            "market_prediction": self.market_prediction.to_dict(),
            "predicted_side": self.predicted_side,
        }
