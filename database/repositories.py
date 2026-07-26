from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from database import models as orm
from datahub import models as hub


class SportsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_league(self, league: hub.League) -> orm.League:
        instance = self.session.scalar(
            select(orm.League).where(
                orm.League.provider == league.provider,
                orm.League.provider_league_id == league.id,
            )
        )
        if instance is None:
            instance = orm.League(provider=league.provider, provider_league_id=league.id, name=league.name)
            self.session.add(instance)
        instance.name = league.name
        instance.country = league.country
        instance.sport = league.sport
        return instance

    def upsert_team(self, team: hub.Team) -> orm.Team:
        instance = self.session.scalar(
            select(orm.Team).where(
                orm.Team.provider == team.provider,
                orm.Team.provider_team_id == team.id,
            )
        )
        if instance is None:
            instance = orm.Team(provider=team.provider, provider_team_id=team.id, name=team.name)
            self.session.add(instance)
        instance.name = team.name
        instance.abbreviation = team.abbreviation
        instance.country = team.country
        return instance

    def upsert_fixture(self, fixture: hub.Fixture) -> orm.Fixture:
        league = self.upsert_league(fixture.league)
        home_team = self.upsert_team(fixture.home_team)
        away_team = self.upsert_team(fixture.away_team)
        self.session.flush()
        instance = self.session.scalar(
            select(orm.Fixture).where(
                orm.Fixture.provider == fixture.provider,
                orm.Fixture.provider_fixture_id == fixture.id,
            )
        )
        if instance is None:
            instance = orm.Fixture(
                provider=fixture.provider,
                provider_fixture_id=fixture.id,
                league=league,
                home_team=home_team,
                away_team=away_team,
                start_time=fixture.start_time,
                status=fixture.status.value,
            )
            self.session.add(instance)
        instance.sport = fixture.sport
        instance.league = league
        instance.home_team = home_team
        instance.away_team = away_team
        instance.start_time = fixture.start_time
        instance.status = fixture.status.value
        instance.venue = fixture.venue
        instance.season = fixture.season
        instance.round_name = fixture.round_name
        instance.raw = fixture.raw
        return instance

    def get_fixture_by_provider_id(self, provider: str, fixture_id: str) -> orm.Fixture | None:
        return self.session.scalar(
            select(orm.Fixture).where(
                orm.Fixture.provider == provider,
                orm.Fixture.provider_fixture_id == fixture_id,
            )
        )

    def add_odds_snapshot(self, fixture: orm.Fixture, odds: hub.Odds, stage: str = "pre_match") -> orm.OddsSnapshot:
        snapshot = orm.OddsSnapshot(
            fixture=fixture,
            provider=odds.provider,
            bookmaker=odds.bookmaker,
            market=odds.market.value,
            line=odds.line,
            home=odds.home,
            draw=odds.draw,
            away=odds.away,
            over=odds.over,
            under=odds.under,
            stage=stage,
            captured_at=odds.captured_at,
            raw=odds.raw,
        )
        self.session.add(snapshot)
        return snapshot

    def add_statistics(self, fixture: orm.Fixture, statistics: hub.Statistics, stage: str = "pre_match") -> orm.MatchStatistics:
        snapshot = orm.MatchStatistics(
            fixture=fixture,
            provider=statistics.provider,
            captured_at=statistics.captured_at,
            stage=stage,
            home_possession=statistics.home_possession,
            away_possession=statistics.away_possession,
            home_shots=statistics.home_shots,
            away_shots=statistics.away_shots,
            home_shots_on_target=statistics.home_shots_on_target,
            away_shots_on_target=statistics.away_shots_on_target,
            home_corners=statistics.home_corners,
            away_corners=statistics.away_corners,
            home_red_cards=statistics.home_red_cards,
            away_red_cards=statistics.away_red_cards,
            raw=statistics.raw,
        )
        self.session.add(snapshot)
        return snapshot

    def save_prediction(
        self,
        fixture: orm.Fixture,
        hunter_score: float,
        grade: str,
        confidence: float,
        risk_level: str,
        risk_score: float,
        signal: str,
        stake: float,
        priority: int,
        reason: str,
        feature_json: dict,
        breakdown_json: dict,
        predicted_side: str | None = None,
    ) -> orm.Prediction:
        prediction = orm.Prediction(
            fixture=fixture,
            predicted_side=predicted_side,
            hunter_score=hunter_score,
            grade=grade,
            confidence=confidence,
            risk_level=risk_level,
            risk_score=risk_score,
            signal=signal,
            stake=stake,
            priority=priority,
            reason=reason,
            feature_json=feature_json,
            breakdown_json=breakdown_json,
        )
        self.session.add(prediction)
        return prediction

    def add_sync_log(
        self,
        provider: str,
        sync_type: str,
        status: str,
        synced_count: int = 0,
        failed_count: int = 0,
        started_at: datetime | None = None,
        error: str | None = None,
    ) -> orm.SyncLog:
        now = datetime.now(timezone.utc)
        log = orm.SyncLog(
            provider=provider,
            sync_type=sync_type,
            status=status,
            started_at=started_at or now,
            finished_at=now,
            synced_count=synced_count,
            failed_count=failed_count,
            error=error,
        )
        self.session.add(log)
        return log


class HistoryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def recent_fixtures(self, limit: int = 100) -> list[orm.Fixture]:
        return list(
            self.session.scalars(select(orm.Fixture).order_by(orm.Fixture.start_time.desc()).limit(limit))
        )

    def by_league(self, league_id: int, limit: int = 1000) -> list[orm.Fixture]:
        return list(
            self.session.scalars(
                select(orm.Fixture)
                .where(orm.Fixture.league_id == league_id)
                .order_by(orm.Fixture.start_time.desc())
                .limit(limit)
            )
        )

    def by_team(self, team_id: int, limit: int = 1000) -> list[orm.Fixture]:
        return list(
            self.session.scalars(
                select(orm.Fixture)
                .where((orm.Fixture.home_team_id == team_id) | (orm.Fixture.away_team_id == team_id))
                .order_by(orm.Fixture.start_time.desc())
                .limit(limit)
            )
        )

    def by_market(self, market: str, limit: int = 1000) -> list[orm.OddsSnapshot]:
        return list(
            self.session.scalars(
                select(orm.OddsSnapshot)
                .where(orm.OddsSnapshot.market == market)
                .order_by(orm.OddsSnapshot.captured_at.desc())
                .limit(limit)
            )
        )
