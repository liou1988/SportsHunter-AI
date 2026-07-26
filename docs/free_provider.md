# Free Provider

Beta v1 defaults to the free football provider:

- `DATA_PROVIDER=free`
- `FOOTBALL_DATA_SOURCE=free`
- `FOOTBALL_DATA_SEASON=2026`

The adapter uses ESPN public Site API endpoints for football scoreboards,
summaries and standings. It checks every league configured in
`FREE_PROVIDER_FOOTBALL_LEAGUES`, aggregates today's fixtures, and de-duplicates
fixtures by provider event id. It returns real feed data only. When odds or
advanced statistics are absent from the feed, SportsHunter-AI returns an empty
result or raises the normalized provider exception instead of silently switching
to Mock.
