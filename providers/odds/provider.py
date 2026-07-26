from __future__ import annotations

from datahub.hub import DataHub
from datahub.models import Odds


class OddsProvider:
    def __init__(self, datahub: DataHub) -> None:
        self.datahub = datahub

    def get_odds(self, fixture_id: str) -> list[Odds]:
        return self.datahub.get_odds(fixture_id)
