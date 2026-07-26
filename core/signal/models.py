from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Signal(StrEnum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    WATCH = "WATCH"
    PASS = "PASS"
    BLOCK = "BLOCK"


@dataclass(slots=True)
class SignalBreakdown:
    reasons: list[str]

    def to_dict(self) -> dict:
        return {"reasons": self.reasons}


@dataclass(slots=True)
class SignalResult:
    signal: Signal
    stake: float
    priority: int
    reason: str
    breakdown: SignalBreakdown

    def to_dict(self) -> dict:
        return {
            "signal": self.signal.value,
            "stake": self.stake,
            "priority": self.priority,
            "reason": self.reason,
            "breakdown": self.breakdown.to_dict(),
        }
