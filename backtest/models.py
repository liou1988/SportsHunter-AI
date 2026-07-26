from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class BacktestMatch:
    fixture_id: str
    league: str
    odds: float
    signal: str
    won: bool
    stake: float = 1.0


@dataclass(slots=True)
class BacktestReport:
    total: int
    win_rate: float
    roi: float
    average_odds: float
    max_winning_streak: int
    max_losing_streak: int
    by_league: dict[str, float] = field(default_factory=dict)
    by_signal: dict[str, float] = field(default_factory=dict)
