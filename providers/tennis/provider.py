from __future__ import annotations

from config.settings import Settings
from datahub.provider import BaseProvider, ProviderUnavailableError


class TennisProvider(BaseProvider):
    name = "tennis"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)

    def _unavailable(self, *args, **kwargs):
        raise ProviderUnavailableError(self.name, "tennis real source is not enabled in Beta v1")

    get_today_fixtures = get_fixture = get_live_matches = get_odds = get_statistics = get_standings = _unavailable
