from __future__ import annotations

from datahub.provider import BaseProvider, ProviderHealth


class ProviderHealthCheck:
    def __init__(self, provider: BaseProvider) -> None:
        self.provider = provider

    def run(self) -> ProviderHealth:
        return self.provider.health_check()
