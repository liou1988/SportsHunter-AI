from __future__ import annotations

from datetime import datetime, timedelta, timezone

from config.settings import Settings
from datahub.models import Fixture, FixtureStatus, League, Odds, OddsMarket, Score, Standing, Statistics, Team
from datahub.provider import BaseProvider


class MockProvider(BaseProvider):
    name = "mock"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.league = League(id="mock-premier", name="Mock Premier League", country="GB", provider=self.name)
        self.home = Team(id="mock-home", name="North City", abbreviation="NOR", provider=self.name)
        self.away = Team(id="mock-away", name="South United", abbreviation="SOU", provider=self.name)

    def _fixture(self, fixture_id: str = "mock-001") -> Fixture:
        return Fixture(
            id=fixture_id,
            league=self.league,
            home_team=self.home,
            away_team=self.away,
            start_time=datetime.now(timezone.utc) + timedelta(hours=5),
            status=FixtureStatus.SCHEDULED,
            venue="Hunter Arena",
            season=self.settings.football_data_season,
            provider=self.name,
            score=Score(),
        )

    def get_today_fixtures(self) -> list[Fixture]:
        return [self._fixture()]

    def get_fixture(self, fixture_id: str) -> Fixture:
        return self._fixture(fixture_id)

    def get_live_matches(self) -> list[Fixture]:
        fixture = self._fixture("mock-live-001")
        fixture.status = FixtureStatus.LIVE
        fixture.score = Score(home=1, away=0, period="2H", clock="63:00")
        return [fixture]

    def get_odds(self, fixture_id: str) -> list[Odds]:
        return [
            Odds(
                fixture_id=fixture_id,
                market=OddsMarket.EUROPEAN,
                bookmaker="MockBook",
                home=1.85,
                draw=3.40,
                away=4.20,
                provider=self.name,
            ),
            Odds(
                fixture_id=fixture_id,
                market=OddsMarket.TOTALS,
                bookmaker="MockBook",
                line=2.5,
                over=1.95,
                under=1.90,
                provider=self.name,
            ),
        ]

    def get_statistics(self, fixture_id: str) -> Statistics:
        return Statistics(
            fixture_id=fixture_id,
            home_possession=58.0,
            away_possession=42.0,
            home_shots=14,
            away_shots=8,
            home_shots_on_target=6,
            away_shots_on_target=3,
            home_corners=7,
            away_corners=2,
            home_red_cards=0,
            away_red_cards=0,
            provider=self.name,
        )

    def get_standings(self, league: str) -> list[Standing]:
        return [
            Standing(league_id=league, team=self.home, rank=2, points=52, played=24, provider=self.name),
            Standing(league_id=league, team=self.away, rank=9, points=34, played=24, provider=self.name),
        ]
