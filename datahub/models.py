from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class FixtureStatus(StrEnum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    FINISHED = "finished"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class OddsMarket(StrEnum):
    EUROPEAN = "european"
    ASIAN_HANDICAP = "asian_handicap"
    TOTALS = "totals"


@dataclass(slots=True)
class League:
    id: str
    name: str
    country: str | None = None
    sport: str = "football"
    provider: str = "unknown"


@dataclass(slots=True)
class Team:
    id: str
    name: str
    abbreviation: str | None = None
    country: str | None = None
    provider: str = "unknown"


@dataclass(slots=True)
class Score:
    home: int | None = None
    away: int | None = None
    period: str | None = None
    clock: str | None = None


@dataclass(slots=True)
class Fixture:
    id: str
    league: League
    home_team: Team
    away_team: Team
    start_time: datetime
    sport: str = "football"
    status: FixtureStatus = FixtureStatus.SCHEDULED
    venue: str | None = None
    season: int | None = None
    round_name: str | None = None
    score: Score | None = None
    provider: str = "unknown"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Odds:
    fixture_id: str
    market: OddsMarket
    bookmaker: str
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    home: float | None = None
    draw: float | None = None
    away: float | None = None
    line: float | None = None
    over: float | None = None
    under: float | None = None
    provider: str = "unknown"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Statistics:
    fixture_id: str
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    home_possession: float | None = None
    away_possession: float | None = None
    home_shots: int | None = None
    away_shots: int | None = None
    home_shots_on_target: int | None = None
    away_shots_on_target: int | None = None
    home_corners: int | None = None
    away_corners: int | None = None
    home_red_cards: int | None = None
    away_red_cards: int | None = None
    provider: str = "unknown"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Standing:
    league_id: str
    team: Team
    rank: int | None = None
    points: int | None = None
    played: int | None = None
    wins: int | None = None
    draws: int | None = None
    losses: int | None = None
    provider: str = "unknown"
    raw: dict[str, Any] = field(default_factory=dict)


def to_plain_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: to_plain_dict(item) for key, item in asdict(value).items()}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, list):
        return [to_plain_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_plain_dict(item) for key, item in value.items()}
    return value
