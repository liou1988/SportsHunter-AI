from __future__ import annotations

import logging
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from config.settings import Settings
from datahub.http_client import HttpJsonClient
from datahub.models import (
    Fixture,
    FixtureStatus,
    League,
    Odds,
    OddsMarket,
    Score,
    Standing,
    Statistics,
    Team,
    to_plain_dict,
)
from datahub.odds_aggregator import build_odds_aggregator
from datahub.provider import BaseProvider, ProviderUnavailableError

logger = logging.getLogger(__name__)


LEAGUE_NAMES = {
    "eng.1": "English Premier League",
    "eng.2": "English League Championship",
    "eng.3": "English League One",
    "eng.4": "English League Two",
    "eng.5": "English National League",
    "eng.fa": "English FA Cup",
    "eng.fa_qual": "English FA Cup Qualifying",
    "eng.league_cup": "English Carabao Cup",
    "eng.trophy": "English EFL Trophy",
    "eng.charity": "English FA Community Shield",
    "esp.1": "Spanish LaLiga",
    "esp.2": "Spanish LaLiga 2",
    "esp.copa_del_rey": "Spanish Copa del Rey",
    "esp.super_cup": "Spanish Super Cup",
    "ita.1": "Italian Serie A",
    "ita.2": "Italian Serie B",
    "ita.coppa_italia": "Italian Coppa Italia",
    "ita.super_cup": "Italian Super Cup",
    "ger.1": "German Bundesliga",
    "ger.2": "German 2. Bundesliga",
    "ger.dfb_pokal": "German DFB Pokal",
    "ger.super_cup": "German Super Cup",
    "fra.1": "French Ligue 1",
    "fra.2": "French Ligue 2",
    "fra.coupe_de_france": "French Coupe de France",
    "fra.super_cup": "French Super Cup",
    "por.1": "Portuguese Primeira Liga",
    "por.taca.portugal": "Portuguese Taca de Portugal",
    "ned.1": "Dutch Eredivisie",
    "ned.2": "Dutch Keuken Kampioen Divisie",
    "ned.cup": "Dutch KNVB Cup",
    "ned.supercup": "Dutch Johan Cruyff Shield",
    "sco.1": "Scottish Premiership",
    "sco.2": "Scottish Championship",
    "sco.tennents": "Scottish Cup",
    "sco.cis": "Scottish League Cup",
    "sco.challenge": "Scottish Challenge Cup",
    "bel.1": "Belgian Pro League",
    "sui.1": "Swiss Super League",
    "aut.1": "Austrian Bundesliga",
    "den.1": "Danish Superliga",
    "nor.1": "Norwegian Eliteserien",
    "swe.1": "Swedish Allsvenskan",
    "pol.1": "Polish Ekstraklasa",
    "tur.1": "Turkish Super Lig",
    "gre.1": "Greek Super League",
    "rus.1": "Russian Premier League",
    "uefa.champions": "UEFA Champions League",
    "uefa.champions_qual": "UEFA Champions League Qualifying",
    "uefa.europa": "UEFA Europa League",
    "uefa.europa_qual": "UEFA Europa League Qualifying",
    "uefa.europa.conf": "UEFA Europa Conference League",
    "uefa.europa.conf_qual": "UEFA Europa Conference League Qualifying",
    "uefa.super_cup": "UEFA Super Cup",
    "uefa.nations": "UEFA Nations League",
    "uefa.euro": "UEFA European Championship",
    "uefa.euroq": "UEFA European Championship Qualifying",
    "fifa.world": "FIFA World Cup",
    "fifa.wwc": "FIFA Women's World Cup",
    "fifa.cwc": "FIFA Club World Cup",
    "fifa.worldq.uefa": "FIFA World Cup Qualifying - UEFA",
    "fifa.worldq.conmebol": "FIFA World Cup Qualifying - CONMEBOL",
    "fifa.worldq.concacaf": "FIFA World Cup Qualifying - Concacaf",
    "fifa.worldq.afc": "FIFA World Cup Qualifying - AFC",
    "fifa.worldq.caf": "FIFA World Cup Qualifying - CAF",
    "fifa.worldq.ofc": "FIFA World Cup Qualifying - OFC",
    "fifa.friendly": "International Friendly",
    "fifa.friendly.w": "Women's International Friendly",
    "fifa.friendly_u21": "International Friendly U21",
    "fifa.world.u20": "FIFA Under-20 World Cup",
    "fifa.world.u17": "FIFA Under-17 World Cup",
    "club.friendly": "Club Friendly",
    "nonfifa": "Non-FIFA Friendly",
    "conmebol.libertadores": "CONMEBOL Libertadores",
    "conmebol.sudamericana": "CONMEBOL Sudamericana",
    "conmebol.america": "Copa America",
    "concacaf.champions": "Concacaf Champions Cup",
    "concacaf.champions_cup": "Concacaf Champions Cup",
    "concacaf.gold": "Concacaf Gold Cup",
    "concacaf.nations.league": "Concacaf Nations League",
    "afc.champions": "AFC Champions League Elite",
    "afc.cup": "AFC Cup",
    "afc.asian.cup": "AFC Asian Cup",
    "aff.championship": "ASEAN Championship",
    "caf.champions": "CAF Champions League",
    "caf.confed": "CAF Confederation Cup",
    "caf.w.nations": "Women's Africa Cup of Nations",
    "usa.1": "Major League Soccer",
    "usa.nwsl": "NWSL",
    "usa.open": "U.S. Open Cup",
    "usa.usl.1": "USL Championship",
    "usa.usl.l1": "USL League One",
    "mex.1": "Liga MX",
    "mex.2": "Liga de Expansion MX",
    "kor.1": "K League 1",
    "kor.2": "K League 2",
    "jpn.1": "Japanese J.League",
    "jpn.2": "Japanese J2 League",
    "aus.1": "Australian A-League Men",
    "chn.1": "Chinese Super League",
    "idn.1": "Indonesian Super League",
    "tha.1": "Thai League 1",
    "sgp.1": "Singaporean Premier League",
    "ind.1": "Indian Super League",
    "ind.2": "Indian I-League",
    "ksa.1": "Saudi Pro League",
    "isr.1": "Israeli Premier League",
    "rsa.1": "South African Premiership",
    "bra.1": "Brazilian Serie A",
    "bra.2": "Brazilian Serie B",
    "bra.copa_do_brazil": "Copa do Brasil",
    "bra.camp.carioca": "Brazilian Campeonato Carioca",
    "bra.camp.paulista": "Brazilian Campeonato Paulista",
    "bra.camp.gaucho": "Brazilian Campeonato Gaucho",
    "bra.camp.mineiro": "Brazilian Campeonato Mineiro",
    "arg.1": "Argentine Liga Profesional de Futbol",
    "arg.2": "Argentine Primera Nacional",
    "arg.3": "Argentine Primera B",
    "arg.copa": "Copa Argentina",
    "col.1": "Colombian Primera A",
    "col.copa": "Copa Colombia",
    "ecu.1": "LigaPro Ecuador",
    "per.1": "Peruvian Liga 1",
    "uru.1": "Uruguayan Primera Division",
    "uru.2": "Uruguayan Segunda Division",
    "chi.1": "Chilean Primera Division",
    "par.1": "Paraguayan Primera Division",
    "bol.1": "Bolivian Liga Profesional",
    "ven.1": "Venezuelan Primera Division",
    "hon.1": "Honduran Liga Nacional",
    "crc.1": "Costa Rican Primera Division",
    "gua.1": "Guatemalan Liga Nacional",
    "slv.1": "Salvadoran Primera Division",
}


ESPN_UNSUPPORTED_LEAGUES = {"kor.1", "kor.2", "jpn.2", "pol.1"}
THESPORTSDB_SOURCE = "thesportsdb"


class FreeFootballProvider(BaseProvider):
    name = "free"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.client = HttpJsonClient(settings, settings.free_provider_base_url)
        self.thesportsdb_client = HttpJsonClient(
            settings,
            settings.free_provider_thesportsdb_base_url,
        )
        self.odds_aggregator = build_odds_aggregator(settings)

    def get_today_fixtures(self) -> list[Fixture]:
        return self.cached("free:today", self._get_today_fixtures, ttl_seconds=120)

    def debug_today(self) -> dict:
        tz = ZoneInfo(self.settings.timezone)
        now = datetime.now(tz)
        today = now.strftime("%Y%m%d")
        today_iso = now.strftime("%Y-%m-%d")
        sources_checked = self._configured_sources()
        leagues_configured = self._configured_leagues()
        leagues_checked = self._configured_espn_leagues()
        leagues_skipped = [league for league in leagues_configured if league not in leagues_checked]
        request_url = ""
        request_urls: list[str] = []
        errors: list[str] = []
        http_statuses: dict[str, int | None] = {}
        http_status: int | None = None
        fixtures_raw = 0
        fixtures_parsed = 0
        fixtures_per_league: dict[str, int] = {}
        fixtures_per_source: dict[str, int] = {}
        parsed_fixtures: list[Fixture] = []
        first_fixture: dict = {}

        with httpx.Client(timeout=self.settings.provider_timeout_seconds, follow_redirects=True) as client:
            if "espn" in sources_checked:
                debug_results: dict[int, tuple[str, int, int, list[Fixture]]] = {}
                workers = min(8, len(leagues_checked)) or 1
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = {
                        executor.submit(self._debug_espn_scoreboard, client, league_id, today): (index, league_id)
                        for index, league_id in enumerate(leagues_checked)
                    }
                    for future in as_completed(futures):
                        index, league_id = futures[future]
                        try:
                            debug_results[index] = future.result()
                        except Exception as exc:  # noqa: BLE001 - debug endpoint must report provider failures
                            logger.error(
                                "free provider debug request failed",
                                extra={"source": "espn", "league": league_id},
                                exc_info=exc,
                            )
                            fixtures_per_league.setdefault(league_id, 0)
                            http_statuses.setdefault(f"espn:{league_id}", None)
                            errors.append(f"espn:{league_id}: {exc}")

                for index, league_id in enumerate(leagues_checked):
                    result = debug_results.get(index)
                    if result is None:
                        continue
                    response_url, status_code, raw_count, parsed = result
                    request_urls.append(response_url)
                    if not request_url:
                        request_url = response_url
                    http_statuses[f"espn:{league_id}"] = status_code
                    fixtures_raw += raw_count
                    fixtures_per_league[league_id] = len(parsed)
                    fixtures_per_source["espn"] = fixtures_per_source.get("espn", 0) + len(parsed)
                    parsed_fixtures.extend(parsed)

            if THESPORTSDB_SOURCE in sources_checked:
                url = f"{self.settings.free_provider_thesportsdb_base_url.rstrip('/')}/eventsday.php"
                try:
                    response = client.get(url, params={"d": today_iso, "s": "Soccer"})
                    response_url = str(response.url)
                    request_urls.append(response_url)
                    if not request_url:
                        request_url = response_url
                    http_statuses["thesportsdb:eventsday"] = response.status_code
                    payload = response.json()
                    events = payload.get("events", []) or []
                    parsed = self._parse_thesportsdb_events(payload)
                    fixtures_raw += len(events)
                    fixtures_per_source[THESPORTSDB_SOURCE] = len(parsed)
                    for league_key, count in self._fixtures_per_league(parsed).items():
                        fixtures_per_league[league_key] = fixtures_per_league.get(league_key, 0) + count
                    parsed_fixtures.extend(parsed)
                except Exception as exc:  # noqa: BLE001 - debug endpoint must report provider failures
                    logger.error("free provider debug request failed", extra={"source": THESPORTSDB_SOURCE}, exc_info=exc)
                    fixtures_per_source.setdefault(THESPORTSDB_SOURCE, 0)
                    http_statuses.setdefault("thesportsdb:eventsday", None)
                    errors.append(f"thesportsdb:eventsday: {exc}")

        deduped = self._dedupe_fixtures(parsed_fixtures)
        fixtures_parsed = len(deduped)
        first_fixture = to_plain_dict(deduped[0]) if deduped else {}
        non_200 = [status for status in http_statuses.values() if status and status >= 400]
        ok_statuses = [status for status in http_statuses.values() if status is not None]
        http_status = (
            non_200[0]
            if non_200
            else (200 if ok_statuses and all(status == 200 for status in ok_statuses) else None)
        )

        return {
            "provider": self.name,
            "source": ",".join(sources_checked),
            "timezone": self.settings.timezone,
            "today": today,
            "today_iso": today_iso,
            "request_url": request_url,
            "request_urls": request_urls,
            "http_status": http_status,
            "http_statuses": http_statuses,
            "sources_checked": sources_checked,
            "leagues_configured": leagues_configured,
            "leagues_checked": leagues_checked,
            "leagues_skipped": leagues_skipped,
            "fixtures_per_league": fixtures_per_league,
            "fixtures_per_source": fixtures_per_source,
            "fixtures_raw": fixtures_raw,
            "fixtures_parsed": fixtures_parsed,
            "first_fixture": first_fixture,
            "errors": errors,
        }

    def _get_today_fixtures(self) -> list[Fixture]:
        tz = ZoneInfo(self.settings.timezone)
        date_key = datetime.now(tz).strftime("%Y%m%d")
        date_iso = datetime.now(tz).strftime("%Y-%m-%d")
        fixtures: list[Fixture] = []
        failures: list[str] = []
        sources = self._configured_sources()

        if "espn" in sources:
            fixtures.extend(self._get_espn_today_fixtures(date_key, failures))

        if THESPORTSDB_SOURCE in sources:
            try:
                payload = self.retry(
                    "thesportsdb:eventsday",
                    lambda: self.thesportsdb_client.get_json(
                        "/eventsday.php",
                        params={"d": date_iso, "s": "Soccer"},
                    ),
                )
                fixtures.extend(self._parse_thesportsdb_events(payload))
            except Exception as exc:  # noqa: BLE001
                logger.error("free provider eventsday failed", extra={"source": THESPORTSDB_SOURCE}, exc_info=exc)
                failures.append(f"thesportsdb:eventsday: {exc}")
        if not fixtures and failures:
            raise ProviderUnavailableError(self.name, "; ".join(failures))
        return self._dedupe_fixtures(fixtures)

    def get_fixture(self, fixture_id: str) -> Fixture:
        for fixture in self.get_today_fixtures():
            if fixture.id == fixture_id:
                return fixture
        if fixture_id.startswith("tsdb:") and THESPORTSDB_SOURCE in self._configured_sources():
            return self._get_thesportsdb_fixture(fixture_id)
        if "espn" in self._configured_sources():
            fixture = self._get_espn_fixture(fixture_id)
            if fixture is not None:
                return fixture
        raise ProviderUnavailableError(self.name, f"fixture {fixture_id} not found in current free feed")

    def get_fixture_by_context(
        self,
        fixture_id: str,
        league_id: str | None = None,
        kickoff: datetime | None = None,
    ) -> Fixture:
        if fixture_id.startswith("tsdb:"):
            return self._get_thesportsdb_fixture(fixture_id)

        league = str(league_id or "").strip()
        if league and self._espn_league_supported(league):
            if kickoff is not None:
                date_key = kickoff.astimezone(ZoneInfo(self.settings.timezone)).strftime("%Y%m%d")
                fixture = self._get_espn_fixture_from_scoreboard(fixture_id, league, date_key)
                if fixture is not None:
                    return fixture
            fixture = self._get_espn_fixture_from_summary(fixture_id, league)
            if fixture is not None:
                return fixture

        return self.get_fixture(fixture_id)

    def get_live_matches(self) -> list[Fixture]:
        fixtures = [fixture for fixture in self.get_today_fixtures() if fixture.status == FixtureStatus.LIVE]
        if THESPORTSDB_SOURCE in self._configured_sources():
            try:
                payload = self.retry(
                    "thesportsdb:livescore",
                    lambda: self.thesportsdb_client.get_json("/livescore.php", params={"s": "Soccer"}),
                )
                fixtures.extend(self._parse_thesportsdb_live(payload))
            except Exception as exc:  # noqa: BLE001
                logger.error("free provider livescore failed", extra={"source": THESPORTSDB_SOURCE}, exc_info=exc)
        return self._dedupe_fixtures(fixtures)

    def get_odds(self, fixture_id: str) -> list[Odds]:
        fixture = self.get_fixture(fixture_id)
        aggregated_odds = self._aggregated_odds(fixture)
        if self._fixture_source(fixture) == THESPORTSDB_SOURCE:
            return aggregated_odds
        try:
            espn_odds = self._get_espn_odds(fixture)
        except Exception:
            if aggregated_odds:
                return aggregated_odds
            raise
        return _dedupe_odds([*aggregated_odds, *espn_odds])

    def _aggregated_odds(self, fixture: Fixture) -> list[Odds]:
        if self.odds_aggregator is None:
            return []
        try:
            return self.odds_aggregator.get_odds(fixture)
        except Exception as exc:  # noqa: BLE001 - external odds are supplemental
            logger.warning(
                "odds aggregator failed",
                extra={
                    "fixture_id": fixture.id,
                    "provider": getattr(self.odds_aggregator, "name", "unknown"),
                },
                exc_info=exc,
            )
            return []

    def _get_espn_odds(self, fixture: Fixture) -> list[Odds]:
        fixture_id = fixture.id
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
            total_line = self._safe_float(item.get("overUnder"))
            over_odds = self._safe_float(item.get("overOdds"))
            under_odds = self._safe_float(item.get("underOdds"))
            if total_line is None:
                total_line = self._safe_float(
                    item.get("total", {}).get("over", {}).get("close", {}).get("line")
                )
            if over_odds is None:
                over_odds = self._safe_float(
                    item.get("total", {}).get("over", {}).get("close", {}).get("odds")
                )
            if under_odds is None:
                under_odds = self._safe_float(
                    item.get("total", {}).get("under", {}).get("close", {}).get("odds")
                )
            if total_line is not None or over_odds is not None or under_odds is not None:
                odds_items.append(
                    Odds(
                        fixture_id=fixture_id,
                        market=OddsMarket.TOTALS,
                        bookmaker=str(provider),
                        line=total_line,
                        over=over_odds,
                        under=under_odds,
                        provider=self.name,
                        raw=item,
                    )
                )

            spread_line = self._safe_float(item.get("spread"))
            home_spread_odds = self._safe_float(item.get("homeTeamOdds", {}).get("spreadOdds"))
            away_spread_odds = self._safe_float(item.get("awayTeamOdds", {}).get("spreadOdds"))
            if spread_line is None:
                spread_line = self._safe_float(
                    item.get("pointSpread", {}).get("home", {}).get("close", {}).get("line")
                )
            if home_spread_odds is None:
                home_spread_odds = self._safe_float(
                    item.get("pointSpread", {}).get("home", {}).get("close", {}).get("odds")
                )
            if away_spread_odds is None:
                away_spread_odds = self._safe_float(
                    item.get("pointSpread", {}).get("away", {}).get("close", {}).get("odds")
                )
            if spread_line is not None or home_spread_odds is not None or away_spread_odds is not None:
                odds_items.append(
                    Odds(
                        fixture_id=fixture_id,
                        market=OddsMarket.ASIAN_HANDICAP,
                        bookmaker=str(provider),
                        line=spread_line,
                        home=home_spread_odds,
                        away=away_spread_odds,
                        provider=self.name,
                        raw=item,
                    )
                )
        return odds_items

    def get_statistics(self, fixture_id: str) -> Statistics:
        fixture = self.get_fixture(fixture_id)
        if self._fixture_source(fixture) == THESPORTSDB_SOURCE:
            return self._get_thesportsdb_statistics(fixture)
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
        if league.startswith("tsdb:"):
            return self._get_thesportsdb_standings(league)
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

    def _get_espn_today_fixtures(self, date_key: str, failures: list[str]) -> list[Fixture]:
        leagues = self._configured_espn_leagues()
        if not leagues:
            return []

        fixtures_by_index: dict[int, list[Fixture]] = {}
        workers = min(8, len(leagues))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(self._fetch_espn_scoreboard, league_id, date_key): (index, league_id)
                for index, league_id in enumerate(leagues)
            }
            for future in as_completed(futures):
                index, league_id = futures[future]
                try:
                    payload = future.result()
                    fixtures_by_index[index] = self._parse_scoreboard(league_id, payload)
                except Exception as exc:  # noqa: BLE001
                    logger.error("free provider scoreboard failed", extra={"source": "espn", "league": league_id}, exc_info=exc)
                    failures.append(f"espn:{league_id}: {exc}")

        fixtures: list[Fixture] = []
        for index in range(len(leagues)):
            fixtures.extend(fixtures_by_index.get(index, []))
        return fixtures

    def _debug_espn_scoreboard(
        self,
        client: httpx.Client,
        league_id: str,
        date_key: str,
    ) -> tuple[str, int, int, list[Fixture]]:
        path = self._scoreboard_path(league_id)
        url = f"{self.settings.free_provider_base_url.rstrip('/')}{path}"
        response = client.get(url, params={"dates": date_key})
        payload = response.json()
        events = payload.get("events", []) or []
        return str(response.url), response.status_code, len(events), self._parse_scoreboard(league_id, payload)

    def _fetch_espn_scoreboard(self, league_id: str, date_key: str) -> dict:
        return self.retry(
            f"scoreboard:{league_id}",
            lambda league_id=league_id: self.client.get_json(
                self._scoreboard_path(league_id),
                params={"dates": date_key},
            ),
        )

    def _get_thesportsdb_fixture(self, fixture_id: str) -> Fixture:
        event_id = fixture_id.removeprefix("tsdb:")
        payload = self.retry(
            f"thesportsdb:event:{event_id}",
            lambda: self.thesportsdb_client.get_json("/lookupevent.php", params={"id": event_id}),
        )
        fixtures = self._parse_thesportsdb_events(payload)
        if fixtures:
            return fixtures[0]
        raise ProviderUnavailableError(self.name, f"TheSportsDB fixture {fixture_id} not found")

    def _get_espn_fixture(self, fixture_id: str) -> Fixture | None:
        failures: list[str] = []
        for league_id in self._configured_espn_leagues():
            try:
                fixture = self._get_espn_fixture_from_summary(fixture_id, league_id)
                if fixture is not None:
                    return fixture
            except Exception as exc:  # noqa: BLE001 - try the remaining configured leagues
                failures.append(f"{league_id}: {exc}")
        if failures:
            logger.warning("free provider summary fixture lookup failed", extra={"fixture_id": fixture_id})
        return None

    def _get_espn_fixture_from_scoreboard(
        self,
        fixture_id: str,
        league_id: str,
        date_key: str,
    ) -> Fixture | None:
        payload = self._fetch_espn_scoreboard(league_id, date_key)
        for fixture in self._parse_scoreboard(league_id, payload):
            if fixture.id == fixture_id:
                return fixture
        return None

    def _get_espn_fixture_from_summary(self, fixture_id: str, league_id: str) -> Fixture | None:
        payload = self.retry(
            f"summary-fixture:{league_id}:{fixture_id}",
            lambda league_id=league_id: self.client.get_json(
                f"/apis/site/v2/sports/soccer/{league_id}/summary",
                params={"event": fixture_id},
            ),
        )
        fixture = self._parse_summary_fixture(league_id, payload, fixture_id)
        if fixture is not None and fixture.id == fixture_id:
            return fixture
        return None

    def _parse_summary_fixture(self, league_id: str, payload: dict, fixture_id: str) -> Fixture | None:
        header = payload.get("header") or {}
        competitions = header.get("competitions") or payload.get("competitions") or []
        competition = competitions[0] if competitions else {}
        competitors = competition.get("competitors") or []
        if not competitors:
            return None
        event = {
            "id": str(header.get("id") or fixture_id),
            "date": competition.get("date") or header.get("date"),
            "season": header.get("season") or payload.get("season") or {},
            "competitions": [competition],
        }
        parsed = self._parse_scoreboard(league_id, {"events": [event], "leagues": [header.get("league") or {}]})
        return parsed[0] if parsed else None

    def _get_thesportsdb_statistics(self, fixture: Fixture) -> Statistics:
        event_id = fixture.id.removeprefix("tsdb:")
        try:
            payload = self.retry(
                f"thesportsdb:statistics:{event_id}",
                lambda: self.thesportsdb_client.get_json("/lookupevent.php", params={"id": event_id}),
            )
        except Exception:
            payload = {"events": [fixture.raw.get("event", fixture.raw)]}
        event = (payload.get("events") or [fixture.raw.get("event", fixture.raw)])[0]
        return Statistics(
            fixture_id=fixture.id,
            provider=self.name,
            raw={"source": THESPORTSDB_SOURCE, "event": event},
        )

    def _get_thesportsdb_standings(self, league: str) -> list[Standing]:
        league_id = league.removeprefix("tsdb:")
        season = str(self.settings.football_data_season or datetime.now(timezone.utc).year)
        payload = self.retry(
            f"thesportsdb:standings:{league_id}",
            lambda: self.thesportsdb_client.get_json("/lookuptable.php", params={"l": league_id, "s": season}),
        )
        standings: list[Standing] = []
        for entry in payload.get("table", []) or []:
            standings.append(
                Standing(
                    league_id=league,
                    team=Team(
                        id=str(entry.get("idTeam") or entry.get("strTeam") or "unknown"),
                        name=str(entry.get("strTeam") or "Unknown Team"),
                        provider=self.name,
                    ),
                    rank=self._safe_int(entry.get("intRank")),
                    points=self._safe_int(entry.get("intPoints")),
                    played=self._safe_int(entry.get("intPlayed")),
                    wins=self._safe_int(entry.get("intWin")),
                    draws=self._safe_int(entry.get("intDraw")),
                    losses=self._safe_int(entry.get("intLoss")),
                    provider=self.name,
                    raw={"source": THESPORTSDB_SOURCE, "standing": entry},
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
            status = competition.get("status", {}) or {}
            status_type = status.get("type", {}) or {}
            fixture_status = self._map_status(status_type)
            fixtures.append(
                Fixture(
                    id=str(event.get("id")),
                    league=league,
                    home_team=self._parse_team(home_payload.get("team", {})),
                    away_team=self._parse_team(away_payload.get("team", {})),
                    start_time=self._parse_datetime(event.get("date")),
                    status=fixture_status,
                    venue=(competition.get("venue") or {}).get("fullName"),
                    season=self.settings.football_data_season,
                    round_name=event.get("season", {}).get("slug"),
                    score=self._score_for_status(fixture_status, home_payload, away_payload, status, status_type),
                    provider=self.name,
                    raw=event,
                )
            )
        return fixtures

    def _parse_thesportsdb_events(self, payload: dict) -> list[Fixture]:
        fixtures: list[Fixture] = []
        for event in payload.get("events", []) or []:
            fixture = self._parse_thesportsdb_event(event)
            if fixture is not None:
                fixtures.append(fixture)
        return fixtures

    def _parse_thesportsdb_live(self, payload: dict) -> list[Fixture]:
        fixtures: list[Fixture] = []
        for event in payload.get("livescore", []) or []:
            if str(event.get("strSport") or "").lower() != "soccer":
                continue
            fixture = self._parse_thesportsdb_event(event, default_status=FixtureStatus.LIVE)
            if fixture is not None:
                fixtures.append(fixture)
        return fixtures

    def _parse_thesportsdb_event(
        self,
        event: dict,
        default_status: FixtureStatus = FixtureStatus.SCHEDULED,
    ) -> Fixture | None:
        event_id = event.get("idEvent")
        home_name = event.get("strHomeTeam")
        away_name = event.get("strAwayTeam")
        if not event_id or not home_name or not away_name:
            return None

        league_id = str(event.get("idLeague") or event.get("strLeague") or "unknown")
        league = League(
            id=f"tsdb:{league_id}",
            name=str(event.get("strLeague") or f"TheSportsDB {league_id}"),
            sport="football",
            provider=self.name,
        )
        return Fixture(
            id=f"tsdb:{event_id}",
            league=league,
            home_team=Team(
                id=str(event.get("idHomeTeam") or f"tsdb-home:{event_id}"),
                name=str(home_name),
                provider=self.name,
            ),
            away_team=Team(
                id=str(event.get("idAwayTeam") or f"tsdb-away:{event_id}"),
                name=str(away_name),
                provider=self.name,
            ),
            start_time=self._parse_thesportsdb_datetime(event),
            status=self._map_thesportsdb_status(event, default_status),
            venue=event.get("strVenue"),
            season=self._safe_int(event.get("strSeason")),
            round_name=str(event.get("intRound") or "") or None,
            score=Score(
                home=self._safe_int(event.get("intHomeScore")),
                away=self._safe_int(event.get("intAwayScore")),
                period=event.get("strStatus"),
                clock=str(event.get("strProgress") or "") or None,
            ),
            provider=self.name,
            raw={"source": THESPORTSDB_SOURCE, "event": event},
        )

    def _parse_team(self, payload: dict) -> Team:
        return Team(
            id=str(payload.get("id") or payload.get("uid") or payload.get("abbreviation") or payload.get("name")),
            name=str(payload.get("displayName") or payload.get("name") or "Unknown Team"),
            abbreviation=payload.get("abbreviation"),
            provider=self.name,
        )

    def _configured_leagues(self) -> list[str]:
        seen: set[str] = set()
        leagues: list[str] = []
        for league_id in self.settings.free_provider_football_leagues or ["eng.1"]:
            normalized = str(league_id).strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                leagues.append(normalized)
        return leagues or ["eng.1"]

    def _configured_espn_leagues(self) -> list[str]:
        return [league for league in self._configured_leagues() if self._espn_league_supported(league)]

    def _configured_sources(self) -> list[str]:
        seen: set[str] = set()
        sources: list[str] = []
        for source in self.settings.free_provider_sources or ["espn"]:
            normalized = str(source).strip().lower().replace("_", "").replace("-", "")
            if normalized in {"sportsdb", "thesportsdb", "tsdb"}:
                normalized = THESPORTSDB_SOURCE
            if normalized in {"espn", THESPORTSDB_SOURCE} and normalized not in seen:
                seen.add(normalized)
                sources.append(normalized)
        return sources or ["espn"]

    @staticmethod
    def _espn_league_supported(league_id: str) -> bool:
        return league_id not in ESPN_UNSUPPORTED_LEAGUES

    @staticmethod
    def _scoreboard_path(league_id: str) -> str:
        return f"/apis/site/v2/sports/soccer/{league_id}/scoreboard"

    @staticmethod
    def _dedupe_fixtures(fixtures: list[Fixture]) -> list[Fixture]:
        deduped: list[Fixture] = []
        seen_ids: set[tuple[str, str]] = set()
        seen_matches: set[tuple[str, ...]] = set()
        for fixture in fixtures:
            id_key = (fixture.provider, fixture.id)
            match_key = FreeFootballProvider._fixture_identity(fixture)
            if id_key in seen_ids or match_key in seen_matches:
                continue
            seen_ids.add(id_key)
            seen_matches.add(match_key)
            deduped.append(fixture)
        return deduped

    @staticmethod
    def _fixture_identity(fixture: Fixture) -> tuple[str, ...]:
        home = FreeFootballProvider._normalize_identity(fixture.home_team.name)
        away = FreeFootballProvider._normalize_identity(fixture.away_team.name)
        if home and away:
            kickoff = fixture.start_time.astimezone(timezone.utc).strftime("%Y%m%d%H%M")
            return ("match", home, away, kickoff)
        return ("id", fixture.provider, fixture.id)

    @staticmethod
    def _normalize_identity(value: str | None) -> str:
        normalized = unicodedata.normalize("NFKD", value or "")
        ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
        return "".join(char for char in ascii_name.casefold() if char.isalnum())

    @staticmethod
    def _fixtures_per_league(fixtures: list[Fixture]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for fixture in fixtures:
            counts[fixture.league.id] = counts.get(fixture.league.id, 0) + 1
        return counts

    @staticmethod
    def _fixture_source(fixture: Fixture) -> str:
        source = fixture.raw.get("source") if isinstance(fixture.raw, dict) else None
        return str(source or "espn")

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    @staticmethod
    def _parse_thesportsdb_datetime(event: dict) -> datetime:
        timestamp = event.get("strTimestamp")
        if timestamp:
            parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

        date_value = str(event.get("dateEvent") or event.get("dateEventLocal") or "")
        time_value = str(event.get("strTime") or event.get("strEventTime") or "00:00:00")
        if not date_value:
            return datetime.now(timezone.utc)
        if len(time_value) == 5:
            time_value = f"{time_value}:00"
        parsed = datetime.fromisoformat(f"{date_value}T{time_value}")
        return parsed.replace(tzinfo=timezone.utc)

    @staticmethod
    def _map_status(status_type: dict) -> FixtureStatus:
        state = str(status_type.get("state") or "").lower()
        name = str(status_type.get("name") or "").lower()
        description = str(status_type.get("description") or "").lower()
        detail = str(status_type.get("detail") or "").lower()
        status_text = " ".join([name, description, detail])
        completed = bool(status_type.get("completed"))

        if "postpon" in status_text:
            return FixtureStatus.POSTPONED
        if "cancel" in status_text or "abandon" in status_text:
            return FixtureStatus.CANCELLED
        if state == "in":
            return FixtureStatus.LIVE
        if state == "post" and completed:
            return FixtureStatus.FINISHED
        if state == "post" and ("final" in status_text or "full time" in status_text):
            return FixtureStatus.FINISHED
        if state == "pre":
            return FixtureStatus.SCHEDULED
        return FixtureStatus.UNKNOWN

    def _score_for_status(
        self,
        status: FixtureStatus,
        home_payload: dict,
        away_payload: dict,
        competition_status: dict,
        status_type: dict,
    ) -> Score:
        has_match_score = status in {FixtureStatus.LIVE, FixtureStatus.FINISHED}
        return Score(
            home=self._safe_int(home_payload.get("score")) if has_match_score else None,
            away=self._safe_int(away_payload.get("score")) if has_match_score else None,
            period=status_type.get("detail"),
            clock=competition_status.get("displayClock"),
        )

    @staticmethod
    def _map_thesportsdb_status(event: dict, default_status: FixtureStatus) -> FixtureStatus:
        status = str(event.get("strStatus") or "").strip().lower()
        progress = str(event.get("strProgress") or "").strip()
        if "postpon" in status:
            return FixtureStatus.POSTPONED
        if "cancel" in status or "abandon" in status:
            return FixtureStatus.CANCELLED
        if status in {"ft", "aet", "match finished", "finished", "full time"}:
            return FixtureStatus.FINISHED
        if status in {"1h", "2h", "ht", "et", "pen", "live"} or progress:
            return FixtureStatus.LIVE
        return default_status

    @staticmethod
    def _safe_float(value: object) -> float | None:
        if value in (None, ""):
            return None
        if isinstance(value, str):
            match = re.search(r"[-+]?\d+(?:\.\d+)?", value.replace("%", ""))
            if match:
                return float(match.group(0))
        try:
            return float(str(value).replace("%", ""))
        except ValueError:
            return None

    @classmethod
    def _safe_int(cls, value: object) -> int | None:
        parsed = cls._safe_float(value)
        return None if parsed is None else int(parsed)


def _dedupe_odds(odds_items: list[Odds]) -> list[Odds]:
    deduped: list[Odds] = []
    seen: set[tuple[str, str, str, float | None]] = set()
    for odds in odds_items:
        key = (odds.provider, odds.bookmaker, odds.market.value, odds.line)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(odds)
    return deduped
