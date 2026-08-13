from __future__ import annotations

from datetime import date
from pathlib import Path

from config.settings import get_settings
from evaluation.analyzer import EvaluationAnalyzer
from evaluation.dataset import EvaluationDataset
from evaluation.metrics import calculate_metrics
from evaluation.models import EvaluationReport
from evaluation.report import EvaluationReportWriter


class EvaluationRunner:
    def __init__(self, dataset: EvaluationDataset | None = None, reports_dir: Path | None = None) -> None:
        settings = get_settings()
        self.writer = EvaluationReportWriter(reports_dir or settings.reports_dir)
        self.analyzer = EvaluationAnalyzer()
        self.dataset = dataset or EvaluationDataset()

    def run(self, period: str = "daily", rows: list[dict] | None = None) -> EvaluationReport:
        rows = self.dataset.rows(period) if rows is None else rows
        learning_records_created = self.dataset.create_learning_records(rows) if rows else 0
        report = EvaluationReport(
            period=period,
            report_date=date.today(),
            metrics=calculate_metrics(rows),
            settled_count=len(rows),
            learning_records_created=learning_records_created,
            sample_breakdown=_sample_breakdown(rows),
            overview=self.analyzer.overview_notes(rows),
            wins=self.analyzer.win_notes(rows),
            losses=self.analyzer.loss_notes(rows),
            confidence_notes=self.analyzer.confidence_notes(rows),
            risk_notes=self.analyzer.risk_notes(rows),
            module_contributions=self.analyzer.module_contribution_notes(rows),
            module_notes=self.analyzer.module_notes(rows),
        )
        self.writer.write(report)
        return report

    def run_for_days(self, days: int) -> EvaluationReport:
        days = max(1, int(days))
        return self.run(f"last_{days}_days", rows=self.dataset.rows_for_days(days))

    def daily(self) -> EvaluationReport:
        return self.run("daily")

    def weekly(self) -> EvaluationReport:
        return self.run("weekly")

    def monthly(self) -> EvaluationReport:
        return self.run("monthly")


def _sample_breakdown(rows: list[dict]) -> dict[str, int]:
    signals = [str(row.get("signal") or "UNKNOWN").upper() for row in rows]
    actionable_count = sum(1 for row in rows if row.get("actionable", True))
    block_count = sum(1 for signal in signals if signal == "BLOCK")
    return {
        "total_count": len(rows),
        "actionable_count": actionable_count,
        "observation_count": max(0, len(rows) - actionable_count),
        "strong_buy_count": sum(1 for signal in signals if signal == "STRONG_BUY"),
        "buy_count": sum(1 for signal in signals if signal == "BUY"),
        "watch_count": sum(1 for signal in signals if signal == "WATCH"),
        "pass_count": sum(1 for signal in signals if signal == "PASS"),
        "block_count": block_count,
    }
