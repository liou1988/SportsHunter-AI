from __future__ import annotations

from core.risk.models import RiskBreakdown, RiskLevel, RiskReason, RiskResult
from core.risk.rules import RISK_RULES
from core.risk.score import compute_risk_inputs
from features.models import FeatureVector


class RiskEngine:
    def __init__(self, rules: dict | None = None) -> None:
        self.rules = rules or RISK_RULES

    def evaluate(self, vector: FeatureVector) -> RiskResult:
        inputs = compute_risk_inputs(vector)
        items: list[RiskReason] = []
        score = 0.0
        for name, config in self.rules.items():
            value = inputs.get(name, 0.0)
            threshold = float(config["threshold"])
            weight = float(config["weight"])
            if (name in {"data_missing", "red_cards", "provider_anomaly"} and value >= threshold) or (
                name not in {"data_missing", "red_cards", "provider_anomaly"} and value >= threshold
            ):
                contribution = min(weight, weight * max(1.0, value / max(threshold, 1)))
                score += contribution
                items.append(RiskReason(source=name, score=round(contribution, 2), reason=str(config["reason"])))
        score = round(min(100.0, score), 2)
        level = self._level(score, items)
        return RiskResult(
            score=score,
            level=level,
            reasons=[item.reason for item in items],
            breakdown=RiskBreakdown(items=items),
            allow_signal=level not in {RiskLevel.HIGH, RiskLevel.BLOCK},
        )

    @staticmethod
    def _level(score: float, items: list[RiskReason]) -> RiskLevel:
        sources = {item.source for item in items}
        if "provider_anomaly" in sources:
            return RiskLevel.BLOCK
        if score >= 65:
            return RiskLevel.BLOCK
        if score >= 45:
            return RiskLevel.HIGH
        if score >= 20:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW
