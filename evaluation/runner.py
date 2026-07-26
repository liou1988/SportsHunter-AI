from __future__ import annotations

from datetime import date

from config.settings import get_settings
from evaluation.analyzer import EvaluationAnalyzer
from evaluation.metrics import calculate_metrics
from evaluation.models import EvaluationReport
from evaluation.report import EvaluationReportWriter


class EvaluationRunner:
    def __init__(self) -> None:
        settings = get_settings()
        self.writer = EvaluationReportWriter(settings.reports_dir)
        self.analyzer = EvaluationAnalyzer()

    def run(self, period: str = "daily", rows: list[dict] | None = None) -> EvaluationReport:
        rows = rows or []
        report = EvaluationReport(
            period=period,
            report_date=date.today(),
            metrics=calculate_metrics(rows),
            module_notes=self.analyzer.module_notes(rows),
        )
        self.writer.write(report)
        return report

    def daily(self) -> EvaluationReport:
        return self.run("daily")

    def weekly(self) -> EvaluationReport:
        return self.run("weekly")

    def monthly(self) -> EvaluationReport:
        return self.run("monthly")
