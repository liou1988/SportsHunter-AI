from __future__ import annotations

from dataclasses import dataclass

from datahub.hub import DataHub
from datahub.models import Fixture


@dataclass(slots=True)
class MatchScanner:
    datahub: DataHub

    def today(self) -> list[Fixture]:
        return self.datahub.get_today_fixtures()

    def live(self) -> list[Fixture]:
        return self.datahub.get_live_matches()
