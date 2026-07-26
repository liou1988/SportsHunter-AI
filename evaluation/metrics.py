from __future__ import annotations

from evaluation.models import EvaluationMetrics


def calculate_metrics(rows: list[dict]) -> EvaluationMetrics:
    if not rows:
        return EvaluationMetrics()
    total = len(rows)
    wins = sum(1 for row in rows if row.get("won"))
    risk_blocks = sum(1 for row in rows if row.get("risk_blocked_bad_result"))
    stake = sum(float(row.get("stake", 0)) for row in rows) or 1.0
    profit = sum(float(row.get("profit", 0)) for row in rows)
    return EvaluationMetrics(
        hunter_hit_rate=wins / total,
        signal_hit_rate=wins / total,
        risk_effectiveness=risk_blocks / total,
        confidence_calibration_error=abs((wins / total) - (sum(float(row.get("confidence", 0)) for row in rows) / total)),
        roi=profit / stake,
    )
