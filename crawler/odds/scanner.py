from __future__ import annotations

from dataclasses import dataclass

from datahub.hub import DataHub
from datahub.models import Odds


@dataclass(slots=True)
class OddsScanner:
    datahub: DataHub

    def fixture_odds(self, fixture_id: str) -> list[Odds]:
        return self.datahub.get_odds(fixture_id)
