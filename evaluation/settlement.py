from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

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
                if not _can_settle(fixture):
                    summary.skipped_count += 1
                    continue
                try:
                    db_fixture = repo.upsert_fixture(fixture)
                    session.flush()
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


def _can_settle(fixture: Fixture) -> bool:
    return (
        fixture.status == FixtureStatus.FINISHED
        and fixture.score is not None
        and fixture.score.home is not None
        and fixture.score.away is not None
    )
