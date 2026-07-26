from __future__ import annotations

import csv
import json
from dataclasses import asdict
from io import StringIO

from backtest.models import BacktestReport


class BacktestReportFormatter:
    def json(self, report: BacktestReport) -> str:
        return json.dumps(asdict(report), indent=2)

    def csv(self, report: BacktestReport) -> str:
        buffer = StringIO()
        writer = csv.DictWriter(buffer, fieldnames=asdict(report).keys())
        writer.writeheader()
        writer.writerow(asdict(report))
        return buffer.getvalue()

    def markdown(self, report: BacktestReport) -> str:
        return "\n".join(
            [
                "# Backtest Report",
                "",
                f"- Total: {report.total}",
                f"- Win rate: {report.win_rate:.2%}",
                f"- ROI: {report.roi:.2%}",
                f"- Average odds: {report.average_odds:.2f}",
                f"- Max winning streak: {report.max_winning_streak}",
                f"- Max losing streak: {report.max_losing_streak}",
            ]
        )
