# Free Provider

Beta v1 defaults to the free football provider:

- `DATA_PROVIDER=free`
- `FOOTBALL_DATA_SOURCE=free`
- `FOOTBALL_DATA_SEASON=2026`
- `FREE_PROVIDER_SOURCES=espn,thesportsdb`

The adapter uses ESPN public Site API endpoints for football scoreboards,
summaries and standings. It also supports TheSportsDB's free `eventsday` and
`livescore` feeds as supplemental real-data sources.

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
