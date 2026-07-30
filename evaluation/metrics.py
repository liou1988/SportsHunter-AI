from __future__ import annotations

from evaluation.models import EvaluationMetrics


def calculate_metrics(rows: list[dict]) -> EvaluationMetrics:
    if not rows:
        return EvaluationMetrics()
    actionable_rows = [row for row in rows if row.get("actionable", True)]
    scored_rows = actionable_rows or rows
    total = len(scored_rows)
    wins = sum(1 for row in scored_rows if row.get("won"))
    risk_rows = [row for row in rows if str(row.get("risk_level") or "").upper() in {"HIGH", "BLOCK"}]
    risk_blocks = sum(1 for row in risk_rows if row.get("risk_blocked_bad_result"))
    risk_effectiveness = (risk_blocks / len(risk_rows)) if risk_rows else None
    stake = sum(float(row.get("stake", 0)) for row in scored_rows) or 1.0
    profit = sum(float(row.get("profit", 0)) for row in scored_rows)
    return EvaluationMetrics(
        hunter_hit_rate=wins / total,
        signal_hit_rate=wins / total,
        risk_effectiveness=risk_effectiveness,
        confidence_calibration_error=abs((wins / total) - (sum(float(row.get("confidence", 0)) for row in scored_rows) / total)),
        roi=profit / stake,
        by_league=_group_hit_rate(scored_rows, "league"),
        by_market=_market_hit_rates(rows),
    )


def _group_hit_rate(rows: list[dict], key: str) -> dict[str, float]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(key) or "unknown"), []).append(row)
    return {
        group: round(sum(1 for row in items if row.get("won")) / len(items), 4)
        for group, items in grouped.items()
        if items
    }


def _market_hit_rates(rows: list[dict]) -> dict[str, float]:
    grouped: dict[str, list[bool]] = {}
    for row in rows:
        for market, hit in (row.get("market_results") or {}).items():
            if hit is None:
                continue
            grouped.setdefault(str(market), []).append(bool(hit))
    return {
        market: round(sum(1 for hit in hits if hit) / len(hits), 4)
        for market, hits in grouped.items()
        if hits
    }
