from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from config.settings import Settings
from datahub.http_client import HttpJsonClient
from datahub.models import Fixture, FixtureStatus, League, Odds, OddsMarket, Score, Standing, Statistics, Team, to_plain_dict
from datahub.provider import BaseProvider, ProviderUnavailableError

logger = logging.getLogger(__name__)


LEAGUE_NAMES = {
    "eng.1": "English Premier League",
    "esp.1": "Spanish LaLiga",
    "ita.1": "Italian Serie A",
    "ger.1": "German Bundesliga",
    "fra.1": "French Ligue 1",
    "uefa.champions": "UEFA Champions League",
}


class FreeFootballProvider(BaseProvider):
    name = "free"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.client = HttpJsonClient(settings, settings.free_provider_base_url)

    def get_today_fixtures(self) -> list[Fixture]:
        return self.cached("free:today", self._get_today_fixtures, ttl_seconds=120)

    def debug_today(self) -> dict:
        tz = ZoneInfo(self.settings.timezone)
        today = datetime.now(tz).strftime("%Y%m%d")
        league_id = next(iter(self.settings.free_provider_football_leagues), "eng.1")
        path = f"/apis/site/v2/sports/soccer/{league_id}/scoreboard"
        request_url = f"{self.settings.free_provider_base_url.rstrip('/')}{path}?dates={today}"
        errors: list[str] = []
        http_status: int | None = None
        fixtures_raw = 0
        fixtures_parsed = 0
        first_fixture: dict = {}

        try:
            with httpx.Client(timeout=self.settings.provider_timeout_seconds, follow_redirects=True) as client:
                response = client.get(
                    f"{self.settings.free_provider_base_url.rstrip('/')}{path}",
                    params={"dates": today},
                )
                request_url = str(response.url)
                http_status = response.status_code
                payload = response.json()
            events = payload.get("events", []) or []
            fixtures_raw = len(events)
            parsed = self._parse_scoreboard(league_id, payload)
            fixtures_parsed = len(parsed)
            first_fixture = to_plain_dict(parsed[0]) if parsed else {}
        except Exception as exc:  # noqa: BLE001 - debug endpoint must report provider failures
            logger.error("free provider debug request failed", extra={"league": league_id}, exc_info=exc)
            errors.append(str(exc))

        return {
            "provider": self.name,
            "source": self.settings.football_data_source,
            "timezone": self.settings.timezone,
            "today": today,
            "request_url": request_url,
            "http_status": http_status,
            "fixtures_raw": fixtures_raw,
            "fixtures_parsed": fixtures_parsed,
            "first_fixture": first_fixture,
            "errors": errors,
        }

    def _get_today_fixtures(self) -> list[Fixture]:
        tz = ZoneInfo(self.settings.timezone)
        date_key = datetime.now(tz).strftime("%Y%m%d")
        fixtures: list[Fixture] = []
        failures: list[str] = []
        for league_id in self.settings.free_provider_football_leagues:
            try:
                payload = self.retry(
                    f"scoreboard:{league_id}",
                    lambda league_id=league_id: self.client.get_json(
                        f"/apis/site/v2/sports/soccer/{league_id}/scoreboard",
                        params={"dates": date_key},
                    ),
                )
                fixtures.extend(self._parse_scoreboard(league_id, payload))
            except Exception as exc:  # noqa: BLE001
                logger.error("free provider scoreboard failed", extra={"league": league_id}, exc_info=exc)
                failures.append(f"{league_id}: {exc}")
        if not fixtures and failures:
            raise ProviderUnavailableError(self.name, "; ".join(failures))
        return fixtures

    def get_fixture(self, fixture_id: str) -> Fixture:
        for fixture in self.get_today_fixtures():
            if fixture.id == fixture_id:
                return fixture
        raise ProviderUnavailableError(self.name, f"fixture {fixture_id} not found in current free feed")

    def get_live_matches(self) -> list[Fixture]:
        return [fixture for fixture in self.get_today_fixtures() if fixture.status == FixtureStatus.LIVE]

    def get_odds(self, fixture_id: str) -> list[Odds]:
        fixture = self.get_fixture(fixture_id)
        league_id = fixture.league.id
        payload = self.retry(
            f"summary-odds:{fixture_id}",
            lambda: self.client.get_json(
                f"/apis/site/v2/sports/soccer/{league_id}/summary",
                params={"event": fixture_id},
            ),
        )
        odds_items: list[Odds] = []
        for item in payload.get("pickcenter", []) or []:
            provider = item.get("provider", {}).get("name") or item.get("provider", {}).get("id") or "ESPN"
            home = self._safe_float(item.get("homeTeamOdds", {}).get("moneyLine"))
            away = self._safe_float(item.get("awayTeamOdds", {}).get("moneyLine"))
            draw = self._safe_float(item.get("drawOdds", {}).get("moneyLine"))
            if home is not None or away is not None or draw is not None:
                odds_items.append(
                    Odds(
                        fixture_id=fixture_id,
                        market=OddsMarket.EUROPEAN,
                        bookmaker=str(provider),
                        home=home,
                        draw=draw,
                        away=away,
                        provider=self.name,
                        raw=item,
                    )
                )
        return odds_items

    def get_statistics(self, fixture_id: str) -> Statistics:
        fixture = self.get_fixture(fixture_id)
        payload = self.retry(
            f"summary-statistics:{fixture_id}",
            lambda: self.client.get_json(
                f"/apis/site/v2/sports/soccer/{fixture.league.id}/summary",
                params={"event": fixture_id},
            ),
        )
        stats = Statistics(fixture_id=fixture_id, provider=self.name, raw=payload.get("boxscore", {}))
        teams = payload.get("boxscore", {}).get("teams", []) or []
        for team_block in teams:
            home_away = team_block.get("homeAway")
            target = "home" if home_away == "home" else "away"
            for item in team_block.get("statistics", []) or []:
                name = str(item.get("name") or item.get("label") or "").lower()
                value = self._safe_float(item.get("displayValue") or item.get("value"))
                if value is None:
                    continue
                if "possession" in name:
                    setattr(stats, f"{target}_possession", value)
                elif name in {"shots", "total shots"}:
                    setattr(stats, f"{target}_shots", int(value))
                elif "shots on target" in name or "on goal" in name:
                    setattr(stats, f"{target}_shots_on_target", int(value))
                elif "corner" in name:
                    setattr(stats, f"{target}_corners", int(value))
                elif "red card" in name:
                    setattr(stats, f"{target}_red_cards", int(value))
        return stats

    def get_standings(self, league: str) -> list[Standing]:
        payload = self.retry(
            f"standings:{league}",
            lambda: self.client.get_json(f"/apis/site/v2/sports/soccer/{league}/standings"),
        )
        standings: list[Standing] = []
        groups = payload.get("children") or [{"standings": payload.get("standings", {})}]
        for group in groups:
            entries = group.get("standings", {}).get("entries", []) or []
            for entry in entries:
                team_payload = entry.get("team", {})
                stats = {stat.get("name"): stat.get("value") for stat in entry.get("stats", []) or []}
                standings.append(
                    Standing(
                        league_id=league,
                        team=self._parse_team(team_payload),
                        rank=self._safe_int(stats.get("rank") or entry.get("rank")),
                        points=self._safe_int(stats.get("points")),
                        played=self._safe_int(stats.get("gamesPlayed")),
                        wins=self._safe_int(stats.get("wins")),
                        draws=self._safe_int(stats.get("ties") or stats.get("draws")),
                        losses=self._safe_int(stats.get("losses")),
                        provider=self.name,
                        raw=entry,
                    )
                )
        return standings

    def _parse_scoreboard(self, league_id: str, payload: dict) -> list[Fixture]:
        league = League(
            id=league_id,
            name=LEAGUE_NAMES.get(league_id, payload.get("leagues", [{}])[0].get("name", league_id)),
            sport="football",
            provider=self.name,
        )
        fixtures: list[Fixture] = []
        for event in payload.get("events", []) or []:
            competition = (event.get("competitions") or [{}])[0]
            competitors = competition.get("competitors", []) or []
            home_payload = next((item for item in competitors if item.get("homeAway") == "home"), {})
            away_payload = next((item for item in competitors if item.get("homeAway") == "away"), {})
            status_type = competition.get("status", {}).get("type", {})
            fixtures.append(
                Fixture(
                    id=str(event.get("id")),
                    league=league,
                    home_team=self._parse_team(home_payload.get("team", {})),
                    away_team=self._parse_team(away_payload.get("team", {})),
                    start_time=self._parse_datetime(event.get("date")),
                    status=self._map_status(status_type),
                    venue=(competition.get("venue") or {}).get("fullName"),
                    season=self.settings.football_data_season,
                    round_name=event.get("season", {}).get("slug"),
                    score=Score(
                        home=self._safe_int(home_payload.get("score")),
                        away=self._safe_int(away_payload.get("score")),
                        period=status_type.get("detail"),
                        clock=competition.get("status", {}).get("displayClock"),
                    ),
                    provider=self.name,
                    raw=event,
                )
            )
        return fixtures

    def _parse_team(self, payload: dict) -> Team:
        return Team(
            id=str(payload.get("id") or payload.get("uid") or payload.get("abbreviation") or payload.get("name")),
            name=str(payload.get("displayName") or payload.get("name") or "Unknown Team"),
            abbreviation=payload.get("abbreviation"),
            provider=self.name,
        )

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    @staticmethod
    def _map_status(status_type: dict) -> FixtureStatus:
        state = str(status_type.get("state") or "").lower()
        name = str(status_type.get("name") or "").lower()
        if state == "in":
            return FixtureStatus.LIVE
        if state == "post":
            return FixtureStatus.FINISHED
        if "postponed" in name:
            return FixtureStatus.POSTPONED
        if "cancel" in name:
            return FixtureStatus.CANCELLED
        if state == "pre":
            return FixtureStatus.SCHEDULED
        return FixtureStatus.UNKNOWN

    @staticmethod
    def _safe_float(value: object) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(str(value).replace("%", ""))
        except ValueError:
            return None

    @classmethod
    def _safe_int(cls, value: object) -> int | None:
        parsed = cls._safe_float(value)
        return None if parsed is None else int(parsed)
