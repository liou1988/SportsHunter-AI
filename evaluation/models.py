from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(slots=True)
class EvaluationMetrics:
    hunter_hit_rate: float = 0.0
    signal_hit_rate: float = 0.0
    risk_effectiveness: float = 0.0
    confidence_calibration_error: float = 0.0
    roi: float = 0.0
    by_league: dict[str, float] = field(default_factory=dict)
    by_market: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class EvaluationReport:
    period: str
    report_date: date
    metrics: EvaluationMetrics
    settled_count: int = 0
    learning_records_created: int = 0
    wins: list[str] = field(default_factory=list)
    losses: list[str] = field(default_factory=list)
    module_notes: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            f"# SportsHunter-AI {self.period.title()} Evaluation",
            "",
            f"- Date: {self.report_date.isoformat()}",
            f"- Settled predictions: {self.settled_count}",
            f"- Learning records created: {self.learning_records_created}",
            f"- Hunter Score hit rate: {self.metrics.hunter_hit_rate:.2%}",
            f"- Signal hit rate: {self.metrics.signal_hit_rate:.2%}",
            f"- Risk effectiveness: {self.metrics.risk_effectiveness:.2%}",
            f"- Confidence calibration error: {self.metrics.confidence_calibration_error:.4f}",
            f"- ROI: {self.metrics.roi:.2%}",
            "",
            "## League Performance",
            *_format_rate_items(self.metrics.by_league),
            "",
            "## Market Performance",
            *_format_rate_items(self.metrics.by_market),
            "",
            "## Why Wins",
            *_format_list_items(self.wins),
            "",
            "## Why Losses",
            *_format_list_items(self.losses),
            "",
            "## Analysis",
            *_format_list_items(self.module_notes),
        ]
        return "\n".join(lines)


@dataclass(slots=True)
class SettlementSummary:
    checked_count: int = 0
    settled_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0

    def to_dict(self) -> dict:
        return {
            "checked_count": self.checked_count,
            "settled_count": self.settled_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
        }


def _format_rate_items(items: dict[str, float]) -> list[str]:
    if not items:
        return ["- No settled data."]
    return [f"- {name}: {rate:.2%}" for name, rate in sorted(items.items())]


def _format_list_items(items: list[str]) -> list[str]:
    if not items:
        return ["- No data."]
    return [f"- {item}" for item in items]
