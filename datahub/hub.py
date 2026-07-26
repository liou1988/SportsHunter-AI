from __future__ import annotations

from config.settings import Settings, get_settings
from datahub.factory import ProviderFactory
from datahub.models import Fixture, Odds, Standing, Statistics
from datahub.provider import BaseProvider, ProviderHealth


class DataHub:
    def __init__(self, provider: BaseProvider) -> None:
        self.provider = provider

    def get_today_fixtures(self) -> list[Fixture]:
        return self.provider.cached("today_fixtures", self.provider.get_today_fixtures)

    def get_fixture(self, fixture_id: str) -> Fixture:
        return self.provider.cached(f"fixture:{fixture_id}", lambda: self.provider.get_fixture(fixture_id))

    def get_live_matches(self) -> list[Fixture]:
        return self.provider.cached("live_matches", self.provider.get_live_matches, ttl_seconds=30)

    def get_odds(self, fixture_id: str) -> list[Odds]:
        return self.provider.cached(f"odds:{fixture_id}", lambda: self.provider.get_odds(fixture_id), ttl_seconds=60)

    def get_statistics(self, fixture_id: str) -> Statistics:
        return self.provider.cached(
            f"statistics:{fixture_id}",
            lambda: self.provider.get_statistics(fixture_id),
            ttl_seconds=60,
        )

    def get_standings(self, league: str) -> list[Standing]:
        return self.provider.cached(f"standings:{league}", lambda: self.provider.get_standings(league))

    def provider_status(self) -> ProviderHealth:
        return self.provider.health_check()


def build_datahub(settings: Settings | None = None) -> DataHub:
    settings = settings or get_settings()
    return DataHub(ProviderFactory.create(settings))
