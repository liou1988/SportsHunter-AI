from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    BLOCK = "BLOCK"


@dataclass(slots=True)
class RiskReason:
    source: str
    score: float
    reason: str


@dataclass(slots=True)
class RiskBreakdown:
    items: list[RiskReason]

    def to_dict(self) -> dict:
        return {"items": [item.__dict__ for item in self.items]}


@dataclass(slots=True)
class RiskResult:
    score: float
    level: RiskLevel
    reasons: list[str]
    breakdown: RiskBreakdown
    allow_signal: bool

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "level": self.level.value,
            "reasons": self.reasons,
            "breakdown": self.breakdown.to_dict(),
            "allow_signal": self.allow_signal,
        }
