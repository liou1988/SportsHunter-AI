from __future__ import annotations

from core.risk.models import RiskLevel
from core.signal.models import Signal
from core.signal.strategy import SIGNAL_STRATEGY


def decide_signal(score: float, risk_level: RiskLevel, confidence: float, strategy: dict | None = None) -> Signal:
    strategy = strategy or SIGNAL_STRATEGY
    if risk_level.value in strategy["block_risk_levels"]:
        return Signal.BLOCK
    strong = strategy["strong_buy"]
    if score >= strong["score"] and risk_level.value == strong["risk"] and confidence >= strong["confidence"]:
        return Signal.STRONG_BUY
    buy = strategy["buy"]
    if score >= buy["score"] and risk_level.value == buy["risk"] and confidence >= buy["confidence"]:
        return Signal.BUY
    watch = strategy["watch"]
    if watch["score_min"] <= score < watch["score_max"]:
        return Signal.WATCH
    return Signal.PASS
