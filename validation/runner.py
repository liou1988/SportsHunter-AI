from __future__ import annotations

import logging

from config.settings import Settings
from datahub.factory import ProviderFactory
from datahub.hub import DataHub
from pipeline.context import build_pipeline_context
from pipeline.runner import PredictionPipeline
from validation.models import ValidationFailure, ValidationReport
from validation.report import ValidationReportWriter

logger = logging.getLogger(__name__)


class ValidationRunner:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings(data_provider="free", football_data_source="free")
        self.datahub = DataHub(ProviderFactory.create(self.settings))
        self.pipeline = PredictionPipeline(build_pipeline_context(self.datahub))
        self.writer = ValidationReportWriter()

    def run(self) -> ValidationReport:
        provider_health = self.datahub.provider_status()
        fixtures = self.datahub.get_today_fixtures()
        report = ValidationReport(
            fixture_count=len(fixtures),
            success_count=0,
            failure_count=0,
            provider_status="UP" if provider_health.health else "DOWN",
        )
        for fixture in fixtures:
            try:
                result = self.pipeline.run_fixture(fixture.id)
                report.success_count += 1
                report.hunter_scores.append(result.hunter_score.score)
                report.risks[result.risk.level.value] = report.risks.get(result.risk.level.value, 0) + 1
                report.signals[result.signal.signal.value] = report.signals.get(result.signal.signal.value, 0) + 1
            except Exception as exc:  # noqa: BLE001
                logger.error("validation fixture failed", extra={"fixture_id": fixture.id}, exc_info=exc)
                report.failure_count += 1
                report.failures.append(ValidationFailure(fixture_id=fixture.id, error=str(exc)))
        self.writer.write(report)
        return report
