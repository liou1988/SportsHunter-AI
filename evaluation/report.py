from __future__ import annotations

from pathlib import Path

from evaluation.models import EvaluationReport


class EvaluationReportWriter:
    def __init__(self, reports_dir: Path) -> None:
        self.reports_dir = reports_dir
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def write(self, report: EvaluationReport) -> Path:
        path = self.reports_dir / f"{report.period}_report.md"
        path.write_text(report.to_markdown(), encoding="utf-8")
        return path
