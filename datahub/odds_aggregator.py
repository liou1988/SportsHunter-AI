from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any, Callable

from config.settings import Settings
from datahub.http_client import HttpJsonClient
from datahub.models import Fixture, FixtureStatus, Odds, OddsMarket

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


class ApiFootballOddsProvider:
    name = "api_football"
    _fixtures_by_date_cache: dict[str, tuple[datetime, list[dict[str, Any]]]] = {}
    _odds_cache: dict[tuple[str, str, int], tuple[datetime, list[Odds]]] = {}
    _quota_blocked_until: datetime | None = None

    def __init__(self, settings: Settings, client: HttpJsonClient | None = None) -> None:
        self.settings = settings
        headers = {"x-apisports-key": str(settings.api_football_key)} if settings.api_football_key else {}
        self.client = client or HttpJsonClient(settings, settings.api_football_base_url, headers=headers)
        self.now = lambda: datetime.now(timezone.utc)

    @classmethod
    def clear_shared_state(cls) -> None:
        cls._fixtures_by_date_cache.clear()
        cls._odds_cache.clear()
        cls._quota_blocked_until = None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.odds_aggregator_enabled and self.settings.api_football_key)

    def get_odds(self, fixture: Fixture) -> list[Odds]:
        if not self.enabled or self._quota_blocked() or not self._fixture_is_requestable(fixture):
            return []

        api_fixture = self._match_fixture(fixture)
        api_fixture_id = _api_football_fixture_id(api_fixture)
        if api_fixture_id is None:
            return []

        odds_items: list[Odds] = []
        if fixture.status == FixtureStatus.LIVE and self.settings.api_football_live_odds_enabled:
            odds_items.extend(self._cached_odds(
                ("live", fixture.id, api_fixture_id),
                self.settings.api_football_live_cache_ttl_seconds,
                lambda: self._get_live_odds(fixture, api_fixture_id),
            ))
            if self.settings.api_football_live_include_prematch:
                odds_items.extend(self._cached_odds(
                    ("prematch", fixture.id, api_fixture_id),
                    self.settings.api_football_prematch_cache_ttl_seconds,
                    lambda: self._get_prematch_odds(fixture, api_fixture_id),
                ))
            return odds_items

        odds_items.extend(self._cached_odds(
            ("prematch", fixture.id, api_fixture_id),
            self.settings.api_football_prematch_cache_ttl_seconds,
            lambda: self._get_prematch_odds(fixture, api_fixture_id),
        ))
        return odds_items

    def _match_fixture(self, fixture: Fixture) -> dict[str, Any] | None:
        date_key = _as_utc(fixture.start_time).date().isoformat()
        cache_entry = self._fixtures_by_date_cache.get(date_key)
        now = self._now()
        if cache_entry is not None and cache_entry[0] > now:
            events = cache_entry[1]
        else:
            payload = self._request_json(
                "/fixtures",
                params={
                    "date": date_key,
                    "timezone": "UTC",
                },
            )
            events = _api_football_response_items(payload)
            self._fixtures_by_date_cache[date_key] = (now + timedelta(hours=6), events)
        return _best_api_football_fixture_match(fixture, events)

    def _get_prematch_odds(self, fixture: Fixture, api_fixture_id: int) -> list[Odds]:
        params = self._odds_params(api_fixture_id)
        payload = self._request_json("/odds", params=params)
        odds_items: list[Odds] = []
        for event in _api_football_response_items(payload):
            odds_items.extend(_parse_api_football_prematch_event(fixture, event))
        max_pages = max(1, self.settings.api_football_odds_max_pages)
        total_pages = min(_api_football_total_pages(payload), max_pages)
        for page in range(2, total_pages + 1):
            paged_payload = self._request_json("/odds", params={**params, "page": str(page)})
            for event in _api_football_response_items(paged_payload):
                odds_items.extend(_parse_api_football_prematch_event(fixture, event))
        return odds_items

    def _get_live_odds(self, fixture: Fixture, api_fixture_id: int) -> list[Odds]:
        params = {"fixture": str(api_fixture_id)}
        if self.settings.api_football_bet_ids:
            params["bet"] = ",".join(self.settings.api_football_bet_ids)
        payload = self._request_json("/odds/live", params=params)
        odds_items: list[Odds] = []
        for event in _api_football_response_items(payload):
            odds_items.extend(_parse_api_football_live_event(fixture, event))
        return odds_items

    def _odds_params(self, api_fixture_id: int) -> dict[str, str]:
        params = {"fixture": str(api_fixture_id)}
        if self.settings.api_football_bookmaker_ids:
            params["bookmaker"] = ",".join(self.settings.api_football_bookmaker_ids)
        if self.settings.api_football_bet_ids:
            params["bet"] = ",".join(self.settings.api_football_bet_ids)
        return params

    def _request_json(self, path: str, params: dict[str, object] | None = None) -> dict[str, Any]:
        if self._quota_blocked():
            return {}
        payload = self.client.get_json(path, params=params)
        if _api_football_quota_exhausted(payload):
            blocked_until = _next_utc_reset(self._now())
            type(self)._quota_blocked_until = blocked_until
            logger.warning(
                "api-football quota exhausted; suppressing requests until reset",
                extra={"blocked_until": blocked_until.isoformat()},
            )
        return payload

    def _cached_odds(
        self,
        key: tuple[str, str, int],
        ttl_seconds: int,
        factory: Callable[[], list[Odds]],
    ) -> list[Odds]:
        now = self._now()
        cached = self._odds_cache.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]
        value = factory()
        self._odds_cache[key] = (now + timedelta(seconds=max(0, ttl_seconds)), value)
        return value

    def _fixture_is_requestable(self, fixture: Fixture) -> bool:
        if fixture.status == FixtureStatus.LIVE:
            return True
        if fixture.status != FixtureStatus.SCHEDULED:
            return False
        minutes_to_kickoff = (_as_utc(fixture.start_time) - self._now()).total_seconds() / 60
        return (
            -self.settings.api_football_prematch_grace_minutes
            <= minutes_to_kickoff
            <= self.settings.api_football_prematch_window_minutes
        )

    def _quota_blocked(self) -> bool:
        blocked_until = type(self)._quota_blocked_until
        if blocked_until is None:
            return False
        if blocked_until <= self._now():
            type(self)._quota_blocked_until = None
            return False
        return True

    def _now(self) -> datetime:
        return _as_utc(self.now())


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


def build_odds_aggregator(settings: Settings) -> TheOddsApiOddsProvider | ApiFootballOddsProvider | None:
    provider = (settings.odds_aggregator_provider or "").strip().lower()
    if provider in {"", "none", "off"}:
        return None
    if provider == ApiFootballOddsProvider.name:
        return ApiFootballOddsProvider(settings)
    if provider == TheOddsApiOddsProvider.name:
        return TheOddsApiOddsProvider(settings)
    logger.warning("unsupported odds aggregator configured", extra={"provider": provider})
    return None


def sport_key_for_fixture(fixture: Fixture) -> str | None:
    league_id = str(fixture.league.id or "").strip()
    if league_id.startswith("tsdb:"):
        return None
    return THE_ODDS_API_SPORT_KEYS.get(league_id)


def _api_football_response_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if errors:
        if not _api_football_quota_exhausted(payload):
            logger.warning("api-football returned errors", extra={"errors": errors})
        return []
    response = payload.get("response", []) if isinstance(payload, dict) else []
    return response if isinstance(response, list) else []


def _api_football_quota_exhausted(payload: dict[str, Any]) -> bool:
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if not errors:
        return False
    text = str(errors).casefold()
    return "request limit" in text or "reached the request" in text or "quota" in text


def _next_utc_reset(now: datetime) -> datetime:
    tomorrow = (now + timedelta(days=1)).date()
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 5, tzinfo=timezone.utc)


def _api_football_total_pages(payload: dict[str, Any]) -> int:
    paging = payload.get("paging") if isinstance(payload, dict) else None
    total = _safe_int((paging or {}).get("total"))
    return total or 1


def _api_football_fixture_id(event: dict[str, Any] | None) -> int | None:
    if not event:
        return None
    return _safe_int((event.get("fixture") or {}).get("id"))


def _best_api_football_fixture_match(
    fixture: Fixture,
    events: list[dict[str, Any]],
) -> dict[str, Any] | None:
    ranked = sorted(
        ((_api_football_fixture_match_score(fixture, event), event) for event in events),
        key=lambda item: item[0],
        reverse=True,
    )
    if not ranked or ranked[0][0] < EVENT_MATCH_THRESHOLD:
        return None
    return ranked[0][1]


def _api_football_fixture_match_score(fixture: Fixture, event: dict[str, Any]) -> float:
    teams = event.get("teams") or {}
    home = str((teams.get("home") or {}).get("name") or "")
    away = str((teams.get("away") or {}).get("name") or "")
    same_side = (
        _similarity(fixture.home_team.name, home) + _similarity(fixture.away_team.name, away)
    ) / 2
    reversed_side = (
        _similarity(fixture.home_team.name, away) + _similarity(fixture.away_team.name, home)
    ) / 2
    team_score = max(same_side, reversed_side * 0.92)
    event_time = _parse_datetime((event.get("fixture") or {}).get("date"))
    if event_time is None:
        return team_score
    hours = abs((_as_utc(fixture.start_time) - event_time).total_seconds()) / 3600
    time_score = max(0.0, 1 - hours / ODDS_WINDOW_HOURS)
    return team_score * 0.85 + time_score * 0.15


def _parse_api_football_prematch_event(fixture: Fixture, event: dict[str, Any]) -> list[Odds]:
    odds_items: list[Odds] = []
    captured_at = _parse_datetime(event.get("update")) or datetime.now(timezone.utc)
    for bookmaker in event.get("bookmakers", []) or []:
        bookmaker_name = str(bookmaker.get("name") or bookmaker.get("id") or "API-Football")
        for bet in bookmaker.get("bets", []) or []:
            odds_items.extend(_parse_api_football_bet(fixture, bookmaker_name, captured_at, event, bet))
    return odds_items


def _parse_api_football_live_event(fixture: Fixture, event: dict[str, Any]) -> list[Odds]:
    odds_items: list[Odds] = []
    captured_at = (
        _parse_datetime(event.get("update"))
        or _parse_datetime((event.get("fixture") or {}).get("date"))
        or datetime.now(timezone.utc)
    )

    bookmakers = event.get("bookmakers")
    if isinstance(bookmakers, list):
        for bookmaker in bookmakers:
            bookmaker_name = str(bookmaker.get("name") or bookmaker.get("id") or "API-Football Live")
            for bet in bookmaker.get("bets", []) or bookmaker.get("odds", []) or []:
                odds_items.extend(_parse_api_football_bet(fixture, bookmaker_name, captured_at, event, bet))
        return odds_items

    bookmaker = event.get("bookmaker")
    if isinstance(bookmaker, dict):
        bookmaker_name = str(bookmaker.get("name") or bookmaker.get("id") or "API-Football Live")
    else:
        bookmaker_name = str(bookmaker or "API-Football Live")
    for bet in event.get("odds", []) or event.get("bets", []) or []:
        odds_items.extend(_parse_api_football_bet(fixture, bookmaker_name, captured_at, event, bet))
    return odds_items


def _parse_api_football_bet(
    fixture: Fixture,
    bookmaker: str,
    captured_at: datetime,
    event: dict[str, Any],
    bet: dict[str, Any],
) -> list[Odds]:
    bet_name = str(bet.get("name") or "")
    values = _active_api_football_values(bet.get("values", []) or [])
    if not values:
        return []

    if _is_api_football_h2h_bet(bet, values):
        odds = _parse_api_football_h2h(fixture, bookmaker, captured_at, event, bet, values)
    elif _is_api_football_totals_bet(bet_name, values):
        odds = _parse_api_football_totals(fixture, bookmaker, captured_at, event, bet, values)
    elif _is_api_football_handicap_bet(bet_name, values):
        odds = _parse_api_football_handicap(fixture, bookmaker, captured_at, event, bet, values)
    else:
        odds = None
    return [odds] if odds is not None else []


def _active_api_football_values(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        value
        for value in values
        if str(value.get("suspended") or "").casefold() not in {"true", "1", "yes"}
        and str(value.get("blocked") or "").casefold() not in {"true", "1", "yes"}
    ]


def _is_api_football_h2h_bet(bet: dict[str, Any], values: list[dict[str, Any]]) -> bool:
    bet_id = str(bet.get("id") or "")
    bet_name = str(bet.get("name") or "").strip().casefold()
    value_names = {_api_football_value_label(value).strip().casefold() for value in values}
    return (
        bet_id == "1"
        or bet_name in {"match winner", "1x2", "winner", "fulltime result", "full time result"}
        or {"home", "draw", "away"}.issubset(value_names)
    )


def _is_api_football_totals_bet(bet_name: str, values: list[dict[str, Any]]) -> bool:
    lowered = bet_name.casefold()
    if "over/under" in lowered or "goals over" in lowered or "total" in lowered:
        return True
    labels = [_api_football_value_label(value).casefold() for value in values]
    return any("over" in label for label in labels) and any("under" in label for label in labels)


def _is_api_football_handicap_bet(bet_name: str, values: list[dict[str, Any]]) -> bool:
    lowered = bet_name.casefold()
    if "handicap" in lowered or "spread" in lowered:
        return True
    labels = [_api_football_value_label(value).casefold() for value in values]
    return any("home" in label for label in labels) and any("away" in label for label in labels)


def _parse_api_football_h2h(
    fixture: Fixture,
    bookmaker: str,
    captured_at: datetime,
    event: dict[str, Any],
    bet: dict[str, Any],
    values: list[dict[str, Any]],
) -> Odds | None:
    home = _api_football_side_value(values, "home", fixture.home_team.name)
    away = _api_football_side_value(values, "away", fixture.away_team.name)
    draw = _api_football_named_value(values, {"draw", "x"})
    if home is None and away is None and draw is None:
        return None
    return Odds(
        fixture_id=fixture.id,
        market=OddsMarket.EUROPEAN,
        bookmaker=bookmaker,
        captured_at=captured_at,
        home=_api_football_odd(home) if home else None,
        draw=_api_football_odd(draw) if draw else None,
        away=_api_football_odd(away) if away else None,
        provider=ApiFootballOddsProvider.name,
        raw=_api_football_raw(event, bet),
    )


def _parse_api_football_totals(
    fixture: Fixture,
    bookmaker: str,
    captured_at: datetime,
    event: dict[str, Any],
    bet: dict[str, Any],
    values: list[dict[str, Any]],
) -> Odds | None:
    pair = _api_football_total_pair(values, str(bet.get("name") or ""))
    if pair is None:
        return None
    line, over, under = pair
    return Odds(
        fixture_id=fixture.id,
        market=OddsMarket.TOTALS,
        bookmaker=bookmaker,
        captured_at=captured_at,
        line=line,
        over=_api_football_odd(over) if over else None,
        under=_api_football_odd(under) if under else None,
        provider=ApiFootballOddsProvider.name,
        raw=_api_football_raw(event, bet),
    )


def _parse_api_football_handicap(
    fixture: Fixture,
    bookmaker: str,
    captured_at: datetime,
    event: dict[str, Any],
    bet: dict[str, Any],
    values: list[dict[str, Any]],
) -> Odds | None:
    pair = _api_football_handicap_pair(fixture, values, str(bet.get("name") or ""))
    if pair is None:
        return None
    line, home, away = pair
    return Odds(
        fixture_id=fixture.id,
        market=OddsMarket.ASIAN_HANDICAP,
        bookmaker=bookmaker,
        captured_at=captured_at,
        line=line,
        home=_api_football_odd(home) if home else None,
        away=_api_football_odd(away) if away else None,
        provider=ApiFootballOddsProvider.name,
        raw=_api_football_raw(event, bet),
    )


def _api_football_total_pair(
    values: list[dict[str, Any]],
    fallback_label: str,
) -> tuple[float | None, dict[str, Any] | None, dict[str, Any] | None] | None:
    by_line: dict[float | None, dict[str, Any]] = {}
    for value in values:
        label = _api_football_value_label(value)
        side = _api_football_total_side(label)
        if side is None:
            continue
        line = _api_football_line(value, fallback_label)
        group = by_line.setdefault(line, {})
        group[side] = value
        if _api_football_is_main(value):
            group["main"] = True

    return _select_api_football_pair(by_line, "over", "under", prefer_common_total=True)


def _api_football_handicap_pair(
    fixture: Fixture,
    values: list[dict[str, Any]],
    fallback_label: str,
) -> tuple[float | None, dict[str, Any] | None, dict[str, Any] | None] | None:
    by_line: dict[float | None, dict[str, Any]] = {}
    for value in values:
        side = _api_football_value_side(fixture, value)
        if side is None:
            continue
        value_line = _api_football_line(value, fallback_label)
        line = -value_line if side == "away" and value_line is not None else value_line
        group = by_line.setdefault(line, {})
        group[side] = value
        if _api_football_is_main(value):
            group["main"] = True

    return _select_api_football_pair(by_line, "home", "away")


def _select_api_football_pair(
    by_line: dict[float | None, dict[str, Any]],
    left_key: str,
    right_key: str,
    *,
    prefer_common_total: bool = False,
) -> tuple[float | None, dict[str, Any] | None, dict[str, Any] | None] | None:
    if not by_line:
        return None
    ranked = sorted(
        by_line.items(),
        key=lambda item: (
            item[1].get(left_key) is not None and item[1].get(right_key) is not None,
            bool(item[1].get("main")),
            prefer_common_total and item[0] == 2.5,
            item[0] is not None,
        ),
        reverse=True,
    )
    line, group = ranked[0]
    left = group.get(left_key)
    right = group.get(right_key)
    if left is None and right is None:
        return None
    return line, left, right


def _api_football_total_side(label: str) -> str | None:
    lowered = label.strip().casefold()
    if lowered.startswith("over") or " over " in f" {lowered} ":
        return "over"
    if lowered.startswith("under") or " under " in f" {lowered} ":
        return "under"
    return None


def _api_football_value_side(fixture: Fixture, value: dict[str, Any]) -> str | None:
    label = _api_football_value_label(value)
    lowered = label.strip().casefold()
    if lowered.startswith("home") or lowered == "1":
        return "home"
    if lowered.startswith("away") or lowered == "2":
        return "away"
    if _similarity(fixture.home_team.name, label) >= EVENT_MATCH_THRESHOLD:
        return "home"
    if _similarity(fixture.away_team.name, label) >= EVENT_MATCH_THRESHOLD:
        return "away"
    return None


def _api_football_side_value(
    values: list[dict[str, Any]],
    side: str,
    team_name: str,
) -> dict[str, Any] | None:
    side_names = {"home", "1"} if side == "home" else {"away", "2"}
    for value in values:
        if _api_football_value_label(value).strip().casefold() in side_names:
            return value
    ranked = sorted(
        ((_similarity(team_name, _api_football_value_label(value)), value) for value in values),
        key=lambda item: item[0],
        reverse=True,
    )
    if not ranked or ranked[0][0] < EVENT_MATCH_THRESHOLD:
        return None
    return ranked[0][1]


def _api_football_named_value(values: list[dict[str, Any]], names: set[str]) -> dict[str, Any] | None:
    for value in values:
        if _api_football_value_label(value).strip().casefold() in names:
            return value
    return None


def _api_football_value_label(value: dict[str, Any]) -> str:
    return str(value.get("value") or value.get("name") or value.get("label") or "")


def _api_football_line(value: dict[str, Any], fallback_label: str = "") -> float | None:
    for key in ("handicap", "point", "line"):
        parsed = _safe_float(value.get(key))
        if parsed is not None:
            return parsed
    labels = [_api_football_value_label(value), fallback_label]
    for label in labels:
        matches = re.findall(r"[-+]?\d+(?:\.\d+)?", label)
        if matches:
            return _safe_float(matches[-1])
    return None


def _api_football_odd(value: dict[str, Any]) -> float | None:
    return _safe_float(value.get("odd") or value.get("price"))


def _api_football_is_main(value: dict[str, Any]) -> bool:
    return str(value.get("main") or "").strip().casefold() in {"true", "1", "yes"}


def _api_football_raw(event: dict[str, Any], bet: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": ApiFootballOddsProvider.name,
        "fixture_id": (event.get("fixture") or {}).get("id"),
        "bet_id": bet.get("id"),
        "bet_name": bet.get("name"),
        "market": bet,
    }


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


def _safe_int(value: object) -> int | None:
    parsed = _safe_float(value)
    return None if parsed is None else int(parsed)
