from __future__ import annotations

from core.rating.engine import HunterScore
from core.risk.models import RiskResult
from core.signal.models import Signal, SignalBreakdown, SignalResult
from core.signal.rules import decide_signal
from core.signal.strategy import SIGNAL_STRATEGY
from features.models import FeatureVector


class SignalEngine:
    def __init__(self, strategy: dict | None = None) -> None:
        self.strategy = strategy or SIGNAL_STRATEGY

    def generate(self, hunter_score: HunterScore, risk: RiskResult, vector: FeatureVector) -> SignalResult:
        signal = decide_signal(hunter_score.score, risk.level, hunter_score.confidence, self.strategy)
        reasons = self._reasons(signal, hunter_score, risk, vector)
        config_key = signal.value.lower()
        config = self.strategy.get(config_key, {})
        if signal == Signal.BLOCK:
            config = {"stake": 0.0, "priority": 0}
        return SignalResult(
            signal=signal,
            stake=float(config.get("stake", 0.0)),
            priority=int(config.get("priority", 0)),
            reason="; ".join(reasons),
            breakdown=SignalBreakdown(reasons=reasons),
        )

    @staticmethod
    def _reasons(signal: Signal, hunter_score: HunterScore, risk: RiskResult, vector: FeatureVector) -> list[str]:
        if signal == Signal.BLOCK:
            return risk.reasons or ["Risk engine blocked this fixture"]
        reasons = [hunter_score.explanation]
        if risk.level.value != "LOW":
            reasons.append(f"Risk level is {risk.level.value}")
        if hunter_score.score < 80:
            reasons.append("Hunter Score is below the pass threshold")
        if vector.warnings:
            reasons.append(f"Feature warnings: {', '.join(vector.warnings)}")
        return reasons
