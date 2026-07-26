from __future__ import annotations

from pathlib import Path

from config.settings import get_settings
from validation.models import ValidationReport


class ValidationReportWriter:
    def write(self, report: ValidationReport, path: Path | None = None) -> Path:
        path = path or get_settings().validation_report_path
        path.write_text(report.to_markdown(), encoding="utf-8")
        return path
