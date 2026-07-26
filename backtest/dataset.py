from __future__ import annotations

from backtest.models import BacktestMatch


class BacktestDataset:
    def __init__(self, matches: list[BacktestMatch] | None = None) -> None:
        self.matches = matches or []

    def load(self) -> list[BacktestMatch]:
        return self.matches
