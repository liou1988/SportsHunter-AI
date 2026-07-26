from __future__ import annotations

import pytest

from config.settings import Settings
from datahub.hub import DataHub
from datahub.providers.mock import MockProvider
from pipeline.context import build_pipeline_context
from pipeline.runner import PredictionPipeline


@pytest.fixture
def mock_settings() -> Settings:
    return Settings(data_provider="mock", football_data_source="mock", enable_scheduler=False, _env_file=None)


@pytest.fixture
def mock_pipeline(mock_settings: Settings) -> PredictionPipeline:
    datahub = DataHub(MockProvider(mock_settings))
    return PredictionPipeline(build_pipeline_context(datahub))
