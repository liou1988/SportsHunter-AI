from __future__ import annotations

import logging

from data_sync.models import SyncSummary
from datahub.hub import DataHub, build_datahub
from database.repositories import SportsRepository
from database.session import SessionLocal

logger = logging.getLogger(__name__)


class DataSync:
    def __init__(self, datahub: DataHub | None = None) -> None:
        self.datahub = datahub or build_datahub()

    def sync_today(self) -> SyncSummary:
        return self._sync("daily", include_odds=False, include_statistics=False)

    def sync_live(self) -> SyncSummary:
        return self._sync("live", include_odds=True, include_statistics=True, live_only=True)

    def sync_history(self) -> SyncSummary:
        return self._sync("history", include_odds=True, include_statistics=True)

    def update_odds(self) -> SyncSummary:
        return self._sync("odds", include_odds=True, include_statistics=False)

    def _sync(
        self,
        sync_type: str,
        include_odds: bool,
        include_statistics: bool,
        live_only: bool = False,
    ) -> SyncSummary:
        provider_name = self.datahub.provider.name
        summary = SyncSummary(sync_type=sync_type, provider=provider_name)
        try:
            fixtures = self.datahub.get_live_matches() if live_only else self.datahub.get_today_fixtures()
            with SessionLocal() as session:
                repo = SportsRepository(session)
                for fixture in fixtures:
                    try:
                        db_fixture = repo.upsert_fixture(fixture)
                        session.flush()
                        if include_odds:
                            for odds in self.datahub.get_odds(fixture.id):
                                repo.add_odds_snapshot(db_fixture, odds, stage="live" if live_only else "pre_match")
                        if include_statistics:
                            statistics = self.datahub.get_statistics(fixture.id)
                            repo.add_statistics(db_fixture, statistics, stage="live" if live_only else "pre_match")
                        # Release SQLite's write lock after every fixture. This also
                        # prevents a slow upstream request from holding one long
                        # transaction while other scheduled jobs need the database.
                        session.commit()
                        summary.synced_count += 1
                    except Exception as exc:  # noqa: BLE001
                        # A failed flush leaves SQLAlchemy's session unusable until
                        # rollback. Continue syncing the remaining fixtures cleanly.
                        session.rollback()
                        logger.error("fixture sync failed", extra={"fixture_id": fixture.id}, exc_info=exc)
                        summary.failed_count += 1
                summary.finish()
                repo.add_sync_log(
                    provider=provider_name,
                    sync_type=sync_type,
                    status=summary.status,
                    synced_count=summary.synced_count,
                    failed_count=summary.failed_count,
                    started_at=summary.started_at,
                    error=summary.error,
                )
                session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.error("data sync failed", extra={"sync_type": sync_type}, exc_info=exc)
            summary.failed_count += 1
            summary.status = "failed"
            summary.error = str(exc)
            summary.finish()
        return summary
