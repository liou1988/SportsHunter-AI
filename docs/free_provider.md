# Free Provider

Beta v1 defaults to the free football provider:

- `DATA_PROVIDER=free`
- `FOOTBALL_DATA_SOURCE=free`
- `FOOTBALL_DATA_SEASON=2026`
- `FREE_PROVIDER_SOURCES=espn,thesportsdb`

The adapter uses ESPN public Site API endpoints for football scoreboards,
summaries and standings. It also supports TheSportsDB's free `eventsday` and
`livescore` feeds as supplemental real-data sources.

External bookmaker odds can be enabled as a supplemental source without
replacing the free fixture feed:

- `ODDS_AGGREGATOR_ENABLED=true`
- `ODDS_AGGREGATOR_PROVIDER=api_football`
- `API_FOOTBALL_KEY=<your API-Football key>`
- `API_FOOTBALL_LIVE_ODDS_ENABLED=true`
- `API_FOOTBALL_LIVE_INCLUDE_PREMATCH=false` avoids spending an extra pre-match
  request for every live fixture.
- `API_FOOTBALL_PREMATCH_WINDOW_MINUTES=90` only requests API-Football pre-match
  odds when kickoff is near.
- `API_FOOTBALL_PREMATCH_CACHE_TTL_SECONDS=1800` and
  `API_FOOTBALL_LIVE_CACHE_TTL_SECONDS=300` reuse recent API-Football odds across
  scheduler/API calls.
- `API_FOOTBALL_BOOKMAKER_IDS=` optionally narrows to specific bookmaker IDs.
- `API_FOOTBALL_BET_IDS=` optionally narrows to specific bet IDs.
- `API_FOOTBALL_ODDS_MAX_PAGES=1` keeps the free plan quota conservative; raise
  it to collect more paginated bookmakers per fixture.

The previous The Odds API adapter remains available as an alternative:

- `ODDS_AGGREGATOR_PROVIDER=the_odds_api`
- `THE_ODDS_API_KEY=<your API key>`
- `THE_ODDS_API_REGIONS=uk,eu`
- `THE_ODDS_API_BOOKMAKERS=` optionally narrows to specific bookmaker keys.

When API-Football is enabled, `get_odds` first matches the ESPN/TheSportsDB
fixture to API-Football's fixture ID by team names and kickoff time, then pulls
pre-match odds from `/odds` only inside the configured kickoff window. For live
fixtures it pulls `/odds/live` so in-play prices are preferred when available.
If API-Football reports the daily request limit has been reached, the adapter
suppresses further API-Football requests until the next UTC reset. The adapter maps
Match Winner, Goals Over/Under and Asian Handicap style bets into the existing
European, totals and Asian handicap markets, then prepends those bookmaker odds
ahead of ESPN `pickcenter` odds. This keeps prediction behavior unchanged when
the key is absent while allowing legal pre-match and in-play bookmaker prices to
flow into features, market projections and archived `odds_snapshots`.

`FREE_PROVIDER_FOOTBALL_LEAGUES` controls ESPN league scanning. The default list
now covers major European leagues and cups, South America, North America, Asia,
Africa, international competitions, club friendlies and several lower divisions.
Known ESPN slugs that are not accepted by the Site API are skipped without
switching to Mock; coverage for those regions can still arrive from TheSportsDB.

The provider aggregates today's fixtures, de-duplicates both same-provider event
ids and cross-source team/time matches, and returns real feed data only. When odds
or advanced statistics are absent from the feed, SportsHunter-AI returns an empty
result or raises the normalized provider exception instead of silently switching
to Mock.

Use `GET /api/provider/debug` to inspect `sources_checked`,
`fixtures_per_source`, `fixtures_per_league`, `leagues_checked`,
`leagues_skipped`, `fixtures_raw`, `fixtures_parsed` and provider errors.
