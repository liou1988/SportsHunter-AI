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
    wins: list[str] = field(default_factory=list)
    losses: list[str] = field(default_factory=list)
    module_notes: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        return "\n".join(
            [
                f"# SportsHunter-AI {self.period.title()} Evaluation",
                "",
                f"- Date: {self.report_date.isoformat()}",
                f"- Hunter Score hit rate: {self.metrics.hunter_hit_rate:.2%}",
                f"- Signal hit rate: {self.metrics.signal_hit_rate:.2%}",
                f"- Risk effectiveness: {self.metrics.risk_effectiveness:.2%}",
                f"- Confidence calibration error: {self.metrics.confidence_calibration_error:.4f}",
                f"- ROI: {self.metrics.roi:.2%}",
                "",
                "## Analysis",
                "- Wins are explained by high Hunter contribution and low risk.",
                "- Losses require module-level review before any weight change.",
            ]
        )
