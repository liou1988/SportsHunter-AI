from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from datahub.hub import DataHub
from datahub.models import Fixture, FixtureStatus
from database.repositories import SportsRepository
from database.session import SessionLocal
from evaluation.models import SettlementSummary

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]


class SettlementService:
    def __init__(self, session_factory: SessionFactory = SessionLocal) -> None:
        self.session_factory = session_factory

    def settle_fixtures(self, fixtures: list[Fixture]) -> SettlementSummary:
        summary = SettlementSummary(checked_count=len(fixtures))
        with self.session_factory() as session:
            repo = SportsRepository(session)
            for fixture in fixtures:
                try:
                    db_fixture = repo.upsert_fixture(fixture)
                    session.flush()
                    if not _can_settle(fixture):
                        summary.skipped_count += 1
                        continue
                    repo.upsert_match_result(
                        db_fixture,
                        home_score=fixture.score.home if fixture.score else None,
                        away_score=fixture.score.away if fixture.score else None,
                        raw=fixture.raw,
                    )
                    summary.settled_count += 1
                except Exception as exc:  # noqa: BLE001 - settle all available fixtures
                    logger.exception("fixture settlement failed", extra={"fixture_id": fixture.id}, exc_info=exc)
                    summary.failed_count += 1
            session.commit()
        return summary

    def settle_pending_predictions(
        self,
        datahub: DataHub,
        lookback_days: int = 3,
        limit: int = 200,
    ) -> SettlementSummary:
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=max(1, lookback_days))
        with self.session_factory() as session:
            repo = SportsRepository(session)
            pending = repo.pending_settlement_fixtures(since=since, until=now, limit=limit)
            pending_contexts = [
                {
                    "fixture_id": fixture.provider_fixture_id,
                    "league_id": fixture.league.provider_league_id if fixture.league else None,
                    "kickoff": fixture.start_time,
                }
                for fixture in pending
            ]

        summary = SettlementSummary(checked_count=len(pending_contexts))
        fixtures: list[Fixture] = []
        for context in pending_contexts:
            fixture_id = str(context["fixture_id"])
            try:
                fixtures.append(_lookup_fixture_for_settlement(datahub, context))
            except Exception as exc:  # noqa: BLE001 - keep attempting other archived fixtures
                logger.warning("pending fixture lookup failed", extra={"fixture_id": fixture_id}, exc_info=exc)
                summary.failed_count += 1

        settled = self.settle_fixtures(fixtures)
        summary.settled_count += settled.settled_count
        summary.skipped_count += settled.skipped_count
        summary.failed_count += settled.failed_count
        return summary



def _lookup_fixture_for_settlement(datahub: DataHub, context: dict) -> Fixture:
    provider = getattr(datahub, "provider", None)
    lookup = getattr(provider, "get_fixture_by_context", None)
    fixture_id = str(context["fixture_id"])
    if callable(lookup):
        return lookup(
            fixture_id,
            league_id=context.get("league_id"),
            kickoff=context.get("kickoff"),
        )
    return datahub.get_fixture(fixture_id)

def _can_settle(fixture: Fixture) -> bool:
    return (
        fixture.status == FixtureStatus.FINISHED
        and fixture.score is not None
        and fixture.score.home is not None
        and fixture.score.away is not None
    )
