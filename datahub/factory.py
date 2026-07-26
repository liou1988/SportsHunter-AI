from __future__ import annotations

from config.settings import Settings
from datahub.provider import BaseProvider, ProviderUnavailableError
from datahub.providers.mock import MockProvider


class ProviderFactory:
    @staticmethod
    def create(settings: Settings) -> BaseProvider:
        provider = (settings.data_provider or settings.football_data_source or "free").lower()
        if provider == "mock":
            return MockProvider(settings)
        if provider == "free":
            from free_provider.football import FreeFootballProvider

            return FreeFootballProvider(settings)
        if provider == "api":
            raise ProviderUnavailableError("api", "API provider is reserved but not configured in Beta v1")
        raise ProviderUnavailableError(provider, "unsupported provider")
