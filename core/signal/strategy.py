SIGNAL_STRATEGY = {
    "strong_buy": {"score": 90.0, "risk": "LOW", "confidence": 0.85, "stake": 1.0, "priority": 100},
    "buy": {"score": 82.0, "risk": "LOW", "confidence": 0.0, "stake": 0.75, "priority": 80},
    "watch": {"score_min": 60.0, "score_max": 82.0, "stake": 0.25, "priority": 50},
    "pass": {"score_max": 60.0, "stake": 0.0, "priority": 10},
    "block_risk_levels": ["HIGH", "BLOCK"],
}
