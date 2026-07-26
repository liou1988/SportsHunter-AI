from __future__ import annotations

import logging

from collector.models import CollectionStage, CollectionSummary
from data_sync.engine import DataSync
from database import models as orm
from database.session import SessionLocal
from pipeline.runner import PredictionPipeline

logger = logging.getLogger(__name__)


class HistoricalCollector:
    def __init__(self, pipeline: PredictionPipeline | None = None, sync: DataSync | None = None) -> None:
        self.pipeline = pipeline or PredictionPipeline()
        self.sync = sync or DataSync(self.pipeline.context.datahub)

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
        results = self.pipeline.run_today()
        with SessionLocal() as session:
            session.add(
                orm.CollectionRun(
                    stage=CollectionStage.POST_MATCH.value,
                    status="success",
                    collected_count=len(results),
                )
            )
            session.commit()
        return CollectionSummary(stage=CollectionStage.POST_MATCH, collected_count=len(results))
