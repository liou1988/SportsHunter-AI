from __future__ import annotations

from collections import defaultdict

from backtest.models import BacktestMatch, BacktestReport


class Metrics:
    def calculate(self, matches: list[BacktestMatch]) -> BacktestReport:
        if not matches:
            return BacktestReport(0, 0.0, 0.0, 0.0, 0, 0)
        wins = sum(1 for item in matches if item.won)
        stake = sum(item.stake for item in matches) or 1.0
        returns = sum(item.odds * item.stake for item in matches if item.won)
        return BacktestReport(
            total=len(matches),
            win_rate=wins / len(matches),
            roi=(returns - stake) / stake,
            average_odds=sum(item.odds for item in matches) / len(matches),
            max_winning_streak=_streak(matches, True),
            max_losing_streak=_streak(matches, False),
            by_league=_group_rate(matches, "league"),
            by_signal=_group_rate(matches, "signal"),
        )


def _streak(matches: list[BacktestMatch], won: bool) -> int:
    best = current = 0
    for item in matches:
        current = current + 1 if item.won is won else 0
        best = max(best, current)
    return best


def _group_rate(matches: list[BacktestMatch], attribute: str) -> dict[str, float]:
    groups: dict[str, list[BacktestMatch]] = defaultdict(list)
    for item in matches:
        groups[str(getattr(item, attribute))].append(item)
    return {name: sum(1 for item in rows if item.won) / len(rows) for name, rows in groups.items()}
