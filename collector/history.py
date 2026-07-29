from __future__ import annotations

import logging

from collector.models import CollectionStage, CollectionSummary
from data_sync.engine import DataSync
from database import models as orm
from database.session import SessionLocal
from evaluation.settlement import SettlementService
from pipeline.runner import PredictionPipeline

logger = logging.getLogger(__name__)


class HistoricalCollector:
    def __init__(
        self,
        pipeline: PredictionPipeline | None = None,
        sync: DataSync | None = None,
        settlement: SettlementService | None = None,
    ) -> None:
        self.pipeline = pipeline or PredictionPipeline()
        self.sync = sync or DataSync(self.pipeline.context.datahub)
        self.settlement = settlement or SettlementService()

    def collect_pre_match(self) -> CollectionSummary:
        summary = self.sync.sync_today()
        return CollectionSummary(
            stage=CollectionStage.PRE_MATCH,
            collected_count=summary.synced_count,
            failed_count=summary.failed_count,
        )

    def collect_live(self) -> CollectionSummary:
        summary = self.sync.sync_live()
        return CollectionSummary(
            stage=CollectionStage.LIVE,
            collected_count=summary.synced_count,
            failed_count=summary.failed_count,
        )

    def collect_post_match(self) -> CollectionSummary:
        sync_summary = self.sync.sync_history()
        fixtures = self.pipeline.context.datahub.get_today_fixtures()
        settlement_summary = self.settlement.settle_fixtures(fixtures)
        pending_summary = self.settlement.settle_pending_predictions(self.pipeline.context.datahub)
        settled_count = settlement_summary.settled_count + pending_summary.settled_count
        failed_count = sync_summary.failed_count + settlement_summary.failed_count + pending_summary.failed_count
        with SessionLocal() as session:
            session.add(
                orm.CollectionRun(
                    stage=CollectionStage.POST_MATCH.value,
                    status="success" if failed_count == 0 else "partial",
                    collected_count=settled_count,
                )
            )
            session.commit()
        return CollectionSummary(
            stage=CollectionStage.POST_MATCH,
            collected_count=settled_count,
            failed_count=failed_count,
        )
