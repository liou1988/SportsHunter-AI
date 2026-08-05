from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp, factorial

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from database import models as orm
from database.session import SessionLocal
from datahub.models import Fixture

SessionFactory = Callable[[], Session]

MAX_GOALS = 7
MIN_LEAGUE_MATCHES = 6
DECAY_DAYS = 180.0
TEAM_SHRINKAGE_MATCHES = 8.0


@dataclass(slots=True)
class OutcomeProbabilities:
    home: float
    draw: float
    away: float

    def to_dict(self) -> dict[str, float]:
        return {
            "home": round(self.home, 4),
            "draw": round(self.draw, 4),
            "away": round(self.away, 4),
        }


@dataclass(slots=True)
class ScoreProbability:
    home: int
    away: int
    probability: float

    @property
    def text(self) -> str:
        return f"{self.home}-{self.away}"

    def to_dict(self) -> dict[str, float | int | str]:
        return {
            "home": self.home,
            "away": self.away,
            "probability": round(self.probability, 4),
            "text": self.text,
        }


@dataclass(slots=True)
class LineProbability:
    win: float
    push: float
    lose: float

    @property
    def effective(self) -> float:
        return round(self.win + self.push * 0.5, 4)


@dataclass(slots=True)
class ProbabilityProjection:
    source: str
    sample_count: int
    league_sample_count: int
    home_team_sample_count: int
    away_team_sample_count: int
    expected_home_goals: float
    expected_away_goals: float
    outcomes: OutcomeProbabilities
    scores: list[ScoreProbability]

    @property
    def expected_total(self) -> float:
        return round(self.expected_home_goals + self.expected_away_goals, 2)

    @property
    def expected_margin(self) -> float:
        return round(self.expected_home_goals - self.expected_away_goals, 2)

    def most_likely_scores(self, limit: int = 3) -> list[ScoreProbability]:
        return self.scores[:limit]

    def total_goals_probability(self, line: float, pick: str) -> LineProbability:
        win = push = lose = 0.0
        pick = pick.upper()
        line_parts = _asian_line_parts(line)
        for score in self.scores:
            total = score.home + score.away
            part_probability = score.probability / len(line_parts)
            for line_part in line_parts:
                if total == line_part:
                    push += part_probability
                elif (
                    (pick == "OVER" and total > line_part)
                    or (pick == "UNDER" and total < line_part)
                ):
                    win += part_probability
                else:
                    lose += part_probability
        return LineProbability(win=round(win, 4), push=round(push, 4), lose=round(lose, 4))

    def handicap_probability(self, side: str, line: float) -> LineProbability:
        win = push = lose = 0.0
        line_parts = _asian_line_parts(line)
        for score in self.scores:
            part_probability = score.probability / len(line_parts)
            for line_part in line_parts:
                adjusted_margin = score.home - score.away + line_part
                if side == "away":
                    adjusted_margin = score.away - score.home + line_part
                if adjusted_margin > 0:
                    win += part_probability
                elif adjusted_margin == 0:
                    push += part_probability
                else:
                    lose += part_probability
        return LineProbability(win=round(win, 4), push=round(push, 4), lose=round(lose, 4))

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "sample_count": self.sample_count,
            "league_sample_count": self.league_sample_count,
            "home_team_sample_count": self.home_team_sample_count,
            "away_team_sample_count": self.away_team_sample_count,
            "expected_home_goals": self.expected_home_goals,
            "expected_away_goals": self.expected_away_goals,
            "expected_total": self.expected_total,
            "expected_margin": self.expected_margin,
            "outcomes": self.outcomes.to_dict(),
            "scores": [score.to_dict() for score in self.most_likely_scores()],
        }


@dataclass(slots=True)
class _WeightedStats:
    matches: int = 0
    weight: float = 0.0
    goals_for: float = 0.0
    goals_against: float = 0.0

    @property
    def goals_for_avg(self) -> float | None:
        return self.goals_for / self.weight if self.weight else None

    @property
    def goals_against_avg(self) -> float | None:
        return self.goals_against / self.weight if self.weight else None

    def add(self, goals_for: int, goals_against: int, weight: float) -> None:
        self.matches += 1
        self.weight += weight
        self.goals_for += goals_for * weight
        self.goals_against += goals_against * weight


class HistoricalProbabilityModel:
    def __init__(
        self,
        session_factory: SessionFactory = SessionLocal,
        min_league_matches: int = MIN_LEAGUE_MATCHES,
        max_matches: int = 2000,
    ) -> None:
        self.session_factory = session_factory
        self.min_league_matches = min_league_matches
        self.max_matches = max_matches

    def predict(self, fixture: Fixture) -> ProbabilityProjection | None:
        rows = self._rows(fixture)
        if len(rows) < self.min_league_matches:
            return None

        league_rows = [row for row in rows if row[0].league.provider_league_id == fixture.league.id]
        model_rows = league_rows if len(league_rows) >= self.min_league_matches else rows
        if len(model_rows) < self.min_league_matches:
            return None

        source = (
            "historical_league_poisson"
            if model_rows is league_rows
            else "historical_global_poisson"
        )
        projection = _build_projection(
            fixture,
            model_rows,
            source=source,
            sample_count=len(rows),
            league_sample_count=len(league_rows),
        )
        if (
            projection.source == "historical_global_poisson"
            and projection.league_sample_count == 0
            and projection.home_team_sample_count == 0
            and projection.away_team_sample_count == 0
        ):
            return None
        return projection

    def _rows(self, fixture: Fixture) -> list[tuple[orm.Fixture, orm.MatchResult]]:
        until = _as_utc(fixture.start_time) or datetime.now(timezone.utc)
        with self.session_factory() as session:
            query = (
                select(orm.Fixture, orm.MatchResult)
                .join(orm.MatchResult, orm.MatchResult.fixture_id == orm.Fixture.id)
                .options(
                    joinedload(orm.Fixture.league),
                    joinedload(orm.Fixture.home_team),
                    joinedload(orm.Fixture.away_team),
                )
                .where(
                    orm.Fixture.provider == fixture.provider,
                    orm.Fixture.sport == fixture.sport,
                    orm.Fixture.start_time < until,
                    orm.MatchResult.home_score.is_not(None),
                    orm.MatchResult.away_score.is_not(None),
                )
                .order_by(orm.Fixture.start_time.desc())
                .limit(self.max_matches)
            )
            return [(db_fixture, result) for db_fixture, result in session.execute(query).all()]


def _build_projection(
    fixture: Fixture,
    rows: list[tuple[orm.Fixture, orm.MatchResult]],
    source: str,
    sample_count: int,
    league_sample_count: int,
) -> ProbabilityProjection:
    until = _as_utc(fixture.start_time) or datetime.now(timezone.utc)
    league_home = _WeightedStats()
    league_away = _WeightedStats()
    teams: dict[str, _WeightedStats] = {}

    for db_fixture, result in rows:
        home_score = int(result.home_score or 0)
        away_score = int(result.away_score or 0)
        weight = _time_weight(db_fixture.start_time, until)
        league_home.add(home_score, away_score, weight)
        league_away.add(away_score, home_score, weight)
        home_key = _db_team_key(db_fixture.home_team)
        away_key = _db_team_key(db_fixture.away_team)
        teams.setdefault(home_key, _WeightedStats()).add(home_score, away_score, weight)
        teams.setdefault(away_key, _WeightedStats()).add(away_score, home_score, weight)

    league_for_avg = _safe_avg(
        league_home.goals_for + league_away.goals_for,
        league_home.weight + league_away.weight,
        1.25,
    )
    league_home_avg = league_home.goals_for_avg or 1.32
    league_away_avg = league_away.goals_for_avg or 1.08

    home_stats = teams.get(_hub_team_key(fixture.home_team), _WeightedStats())
    away_stats = teams.get(_hub_team_key(fixture.away_team), _WeightedStats())
    home_attack = _strength_ratio(home_stats.goals_for_avg, league_for_avg, home_stats.matches)
    home_defense = _strength_ratio(home_stats.goals_against_avg, league_for_avg, home_stats.matches)
    away_attack = _strength_ratio(away_stats.goals_for_avg, league_for_avg, away_stats.matches)
    away_defense = _strength_ratio(away_stats.goals_against_avg, league_for_avg, away_stats.matches)

    expected_home = _clip(league_home_avg * home_attack * away_defense, 0.2, 4.5)
    expected_away = _clip(league_away_avg * away_attack * home_defense, 0.2, 4.5)
    scores = _score_grid(expected_home, expected_away)
    outcomes = _outcomes(scores)
    return ProbabilityProjection(
        source=source,
        sample_count=sample_count,
        league_sample_count=league_sample_count,
        home_team_sample_count=home_stats.matches,
        away_team_sample_count=away_stats.matches,
        expected_home_goals=expected_home,
        expected_away_goals=expected_away,
        outcomes=outcomes,
        scores=scores,
    )


def _score_grid(expected_home: float, expected_away: float) -> list[ScoreProbability]:
    scores: list[ScoreProbability] = []
    total_probability = 0.0
    for home_goals in range(MAX_GOALS + 1):
        for away_goals in range(MAX_GOALS + 1):
            probability = _poisson_probability(home_goals, expected_home) * _poisson_probability(
                away_goals,
                expected_away,
            )
            total_probability += probability
            scores.append(
                ScoreProbability(home=home_goals, away=away_goals, probability=probability)
            )
    normalizer = total_probability or 1.0
    normalized = [
        ScoreProbability(
            home=score.home,
            away=score.away,
            probability=score.probability / normalizer,
        )
        for score in scores
    ]
    return sorted(normalized, key=lambda score: score.probability, reverse=True)


def _outcomes(scores: list[ScoreProbability]) -> OutcomeProbabilities:
    home = sum(score.probability for score in scores if score.home > score.away)
    draw = sum(score.probability for score in scores if score.home == score.away)
    away = sum(score.probability for score in scores if score.home < score.away)
    return OutcomeProbabilities(home=home, draw=draw, away=away)


def _poisson_probability(goals: int, expected_goals: float) -> float:
    return exp(-expected_goals) * (expected_goals ** goals) / factorial(goals)


def _asian_line_parts(line: float) -> list[float]:
    rounded = round(line * 4) / 4
    fraction = abs(rounded) % 1
    if abs(fraction - 0.25) < 0.001 or abs(fraction - 0.75) < 0.001:
        return [rounded - 0.25, rounded + 0.25]
    return [rounded]


def _time_weight(start_time: datetime | None, until: datetime) -> float:
    start_time = _as_utc(start_time)
    if start_time is None:
        return 1.0
    days = max(0.0, (until - start_time).total_seconds() / 86400)
    return exp(-days / DECAY_DAYS)


def _strength_ratio(value: float | None, prior: float, matches: int) -> float:
    if value is None or prior <= 0:
        return 1.0
    shrunk = (value * matches + prior * TEAM_SHRINKAGE_MATCHES) / (matches + TEAM_SHRINKAGE_MATCHES)
    return _clip(shrunk / prior, 0.55, 1.65)


def _safe_avg(total: float, weight: float, default: float) -> float:
    return total / weight if weight else default


def _db_team_key(team: orm.Team | None) -> str:
    return str(getattr(team, "provider_team_id", "") or "").casefold().strip()


def _hub_team_key(team: object) -> str:
    return str(getattr(team, "id", "") or "").casefold().strip()


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _clip(value: float, low: float, high: float) -> float:
    return round(max(low, min(high, value)), 2)
