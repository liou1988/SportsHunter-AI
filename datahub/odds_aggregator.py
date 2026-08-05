from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any

from config.settings import Settings
from datahub.http_client import HttpJsonClient
from datahub.models import Fixture, Odds, OddsMarket

logger = logging.getLogger(__name__)

DEFAULT_MARKETS = ["h2h", "spreads", "totals"]
EVENT_MATCH_THRESHOLD = 0.72
ODDS_WINDOW_HOURS = 8

THE_ODDS_API_SPORT_KEYS = {
    "eng.1": "soccer_epl",
    "eng.2": "soccer_efl_champ",
    "esp.1": "soccer_spain_la_liga",
    "esp.2": "soccer_spain_segunda_division",
    "esp.copa_del_rey": "soccer_spain_copa_del_rey",
    "ita.1": "soccer_italy_serie_a",
    "ita.2": "soccer_italy_serie_b",
    "ita.coppa_italia": "soccer_italy_coppa_italia",
    "ger.1": "soccer_germany_bundesliga",
    "ger.2": "soccer_germany_bundesliga2",
    "ger.dfb_pokal": "soccer_germany_dfb_pokal",
    "fra.1": "soccer_france_ligue_one",
    "fra.2": "soccer_france_ligue_two",
    "fra.coupe_de_france": "soccer_france_coupe_de_france",
    "por.1": "soccer_portugal_primeira_liga",
    "ned.1": "soccer_netherlands_eredivisie",
    "sco.1": "soccer_spl",
    "sui.1": "soccer_switzerland_superleague",
    "den.1": "soccer_denmark_superliga",
    "nor.1": "soccer_norway_eliteserien",
    "swe.1": "soccer_sweden_allsvenskan",
    "swe.2": "soccer_sweden_superettan",
    "pol.1": "soccer_poland_ekstraklasa",
    "tur.1": "soccer_turkey_super_league",
    "gre.1": "soccer_greece_super_league",
    "rus.1": "soccer_russia_premier_league",
    "jpn.1": "soccer_japan_j_league",
    "kor.1": "soccer_korea_kleague1",
    "ksa.1": "soccer_saudi_arabia_pro_league",
    "bra.1": "soccer_brazil_campeonato",
    "arg.1": "soccer_argentina_primera_division",
    "usa.1": "soccer_usa_mls",
    "mex.1": "soccer_mexico_ligamx",
    "fifa.cwc": "soccer_fifa_club_world_cup",
    "fifa.world": "soccer_fifa_world_cup",
    "uefa.champions": "soccer_uefa_champs_league",
    "uefa.europa": "soccer_uefa_europa_league",
    "uefa.europa.conf": "soccer_uefa_europa_conference_league",
    "uefa.nations": "soccer_uefa_nations_league",
}


class TheOddsApiOddsProvider:
    name = "the_odds_api"

    def __init__(self, settings: Settings, client: HttpJsonClient | None = None) -> None:
        self.settings = settings
        self.client = client or HttpJsonClient(settings, settings.the_odds_api_base_url)

    @property
    def enabled(self) -> bool:
        return bool(self.settings.odds_aggregator_enabled and self.settings.the_odds_api_key)

    def get_odds(self, fixture: Fixture) -> list[Odds]:
        if not self.enabled:
            return []

        sport_key = sport_key_for_fixture(fixture)
        if sport_key is None:
            return []

        payload = self.client.get_json(f"/v4/sports/{sport_key}/odds", params=self._params(fixture))
        events = payload if isinstance(payload, list) else payload.get("data", [])
        event = _best_event_match(fixture, events)
        if event is None:
            return []
        return _parse_event_odds(fixture, event)

    def _params(self, fixture: Fixture) -> dict[str, str]:
        start = _as_utc(fixture.start_time)
        window_start = start - timedelta(hours=ODDS_WINDOW_HOURS)
        window_end = start + timedelta(hours=ODDS_WINDOW_HOURS)
        params = {
            "apiKey": str(self.settings.the_odds_api_key),
            "markets": ",".join(self.settings.the_odds_api_markets or DEFAULT_MARKETS),
            "oddsFormat": "decimal",
            "dateFormat": "iso",
            "commenceTimeFrom": _iso_z(window_start),
            "commenceTimeTo": _iso_z(window_end),
        }
        bookmakers = ",".join(self.settings.the_odds_api_bookmakers)
        if bookmakers:
            params["bookmakers"] = bookmakers
        else:
            params["regions"] = ",".join(self.settings.the_odds_api_regions or ["uk", "eu"])
        return params


def build_odds_aggregator(settings: Settings) -> TheOddsApiOddsProvider | None:
    provider = (settings.odds_aggregator_provider or "").strip().lower()
    if provider in {"", "none", "off"}:
        return None
    if provider == TheOddsApiOddsProvider.name:
        return TheOddsApiOddsProvider(settings)
    logger.warning("unsupported odds aggregator configured", extra={"provider": provider})
    return None


def sport_key_for_fixture(fixture: Fixture) -> str | None:
    league_id = str(fixture.league.id or "").strip()
    if league_id.startswith("tsdb:"):
        return None
    return THE_ODDS_API_SPORT_KEYS.get(league_id)


def _parse_event_odds(fixture: Fixture, event: dict[str, Any]) -> list[Odds]:
    odds_items: list[Odds] = []
    for bookmaker in event.get("bookmakers", []) or []:
        bookmaker_name = str(bookmaker.get("title") or bookmaker.get("key") or "The Odds API")
        captured_at = _parse_datetime(bookmaker.get("last_update")) or datetime.now(timezone.utc)
        for market in bookmaker.get("markets", []) or []:
            market_key = str(market.get("key") or "").casefold()
            outcomes = market.get("outcomes", []) or []
            if market_key == "h2h":
                odds = _parse_h2h(fixture, bookmaker_name, captured_at, event, market, outcomes)
            elif market_key == "totals":
                odds = _parse_totals(fixture, bookmaker_name, captured_at, event, market, outcomes)
            elif market_key == "spreads":
                odds = _parse_spreads(fixture, bookmaker_name, captured_at, event, market, outcomes)
            else:
                odds = None
            if odds is not None:
                odds_items.append(odds)
    return odds_items


def _parse_h2h(
    fixture: Fixture,
    bookmaker: str,
    captured_at: datetime,
    event: dict[str, Any],
    market: dict[str, Any],
    outcomes: list[dict[str, Any]],
) -> Odds | None:
    home = _team_outcome(outcomes, fixture.home_team.name)
    away = _team_outcome(outcomes, fixture.away_team.name)
    draw = _named_outcome(outcomes, {"draw", "tie"})
    if home is None and away is None and draw is None:
        return None
    return Odds(
        fixture_id=fixture.id,
        market=OddsMarket.EUROPEAN,
        bookmaker=bookmaker,
        captured_at=captured_at,
        home=_safe_float(home.get("price")) if home else None,
        draw=_safe_float(draw.get("price")) if draw else None,
        away=_safe_float(away.get("price")) if away else None,
        provider=TheOddsApiOddsProvider.name,
        raw=_raw(event, market),
    )


def _parse_totals(
    fixture: Fixture,
    bookmaker: str,
    captured_at: datetime,
    event: dict[str, Any],
    market: dict[str, Any],
    outcomes: list[dict[str, Any]],
) -> Odds | None:
    over = _named_outcome(outcomes, {"over"})
    under = _named_outcome(outcomes, {"under"})
    if over is None and under is None:
        return None
    return Odds(
        fixture_id=fixture.id,
        market=OddsMarket.TOTALS,
        bookmaker=bookmaker,
        captured_at=captured_at,
        line=_safe_float((over or under or {}).get("point")),
        over=_safe_float(over.get("price")) if over else None,
        under=_safe_float(under.get("price")) if under else None,
        provider=TheOddsApiOddsProvider.name,
        raw=_raw(event, market),
    )


def _parse_spreads(
    fixture: Fixture,
    bookmaker: str,
    captured_at: datetime,
    event: dict[str, Any],
    market: dict[str, Any],
    outcomes: list[dict[str, Any]],
) -> Odds | None:
    home = _team_outcome(outcomes, fixture.home_team.name)
    away = _team_outcome(outcomes, fixture.away_team.name)
    if home is None and away is None:
        return None
    return Odds(
        fixture_id=fixture.id,
        market=OddsMarket.ASIAN_HANDICAP,
        bookmaker=bookmaker,
        captured_at=captured_at,
        line=_safe_float((home or {}).get("point")),
        home=_safe_float(home.get("price")) if home else None,
        away=_safe_float(away.get("price")) if away else None,
        provider=TheOddsApiOddsProvider.name,
        raw=_raw(event, market),
    )


def _best_event_match(fixture: Fixture, events: list[dict[str, Any]]) -> dict[str, Any] | None:
    ranked = sorted(
        ((_event_match_score(fixture, event), event) for event in events),
        key=lambda item: item[0],
        reverse=True,
    )
    if not ranked or ranked[0][0] < EVENT_MATCH_THRESHOLD:
        return None
    return ranked[0][1]


def _event_match_score(fixture: Fixture, event: dict[str, Any]) -> float:
    home = str(event.get("home_team") or "")
    away = str(event.get("away_team") or "")
    same_side = (
        _similarity(fixture.home_team.name, home) + _similarity(fixture.away_team.name, away)
    ) / 2
    reversed_side = (
        _similarity(fixture.home_team.name, away) + _similarity(fixture.away_team.name, home)
    ) / 2
    team_score = max(same_side, reversed_side * 0.92)
    event_time = _parse_datetime(event.get("commence_time"))
    if event_time is None:
        return team_score
    hours = abs((_as_utc(fixture.start_time) - event_time).total_seconds()) / 3600
    time_score = max(0.0, 1 - hours / ODDS_WINDOW_HOURS)
    return team_score * 0.85 + time_score * 0.15


def _team_outcome(outcomes: list[dict[str, Any]], team_name: str) -> dict[str, Any] | None:
    ranked = sorted(
        ((_similarity(team_name, str(outcome.get("name") or "")), outcome) for outcome in outcomes),
        key=lambda item: item[0],
        reverse=True,
    )
    if not ranked or ranked[0][0] < EVENT_MATCH_THRESHOLD:
        return None
    return ranked[0][1]


def _named_outcome(outcomes: list[dict[str, Any]], names: set[str]) -> dict[str, Any] | None:
    for outcome in outcomes:
        if str(outcome.get("name") or "").strip().casefold() in names:
            return outcome
    return None


def _similarity(left: str | None, right: str | None) -> float:
    left_key = _normalize(left)
    right_key = _normalize(right)
    if not left_key or not right_key:
        return 0.0
    if left_key == right_key:
        return 1.0
    if left_key in right_key or right_key in left_key:
        return 0.9
    return SequenceMatcher(None, left_key, right_key).ratio()


def _normalize(value: str | None) -> str:
    return "".join(char for char in str(value or "").casefold() if char.isalnum())


def _raw(event: dict[str, Any], market: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": TheOddsApiOddsProvider.name,
        "event_id": event.get("id"),
        "sport_key": event.get("sport_key"),
        "commence_time": event.get("commence_time"),
        "market": market,
    }


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso_z(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _safe_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
