from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class WeightAdjustmentSuggestion:
    module: str
    label: str
    current_weight: float
    suggested_weight: float
    delta: float
    direction: str
    reason: str
    evidence: str
    risk: str

    def to_dict(self) -> dict:
        return {
            "module": self.module,
            "label": self.label,
            "current_weight": self.current_weight,
            "suggested_weight": self.suggested_weight,
            "delta": self.delta,
            "direction": self.direction,
            "reason": self.reason,
            "evidence": self.evidence,
            "risk": self.risk,
        }


@dataclass(slots=True)
class OptimizerReport:
    status: str
    can_apply: bool
    sample_count: int
    min_recommended_sample: int
    wins: int
    losses: int
    hit_rate: float
    roi: float
    confidence_error: float
    current_weights: dict[str, float]
    suggested_weights: dict[str, float]
    suggestions: list[WeightAdjustmentSuggestion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "status_label": _status_label(self.status),
            "can_apply": self.can_apply,
            "sample_count": self.sample_count,
            "min_recommended_sample": self.min_recommended_sample,
            "wins": self.wins,
            "losses": self.losses,
            "hit_rate": self.hit_rate,
            "roi": self.roi,
            "confidence_error": self.confidence_error,
            "current_weights": self.current_weights,
            "suggested_weights": self.suggested_weights,
            "suggestions": [item.to_dict() for item in self.suggestions],
            "warnings": self.warnings,
            "generated_at": self.generated_at.isoformat(),
        }


def _status_label(status: str) -> str:
    return {
        "ready": "可应用",
        "observe": "观察中",
        "stable": "暂不调整",
        "empty": "暂无样本",
    }.get(status, status)
