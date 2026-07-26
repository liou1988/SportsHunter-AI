from __future__ import annotations

from backtest.dataset import BacktestDataset
from backtest.metrics import Metrics
from backtest.models import BacktestReport


class BacktestRunner:
    def __init__(self, dataset: BacktestDataset | None = None, metrics: Metrics | None = None) -> None:
        self.dataset = dataset or BacktestDataset()
        self.metrics = metrics or Metrics()

    def run(self) -> BacktestReport:
        return self.metrics.calculate(self.dataset.load())
