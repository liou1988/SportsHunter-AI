# Free Provider

Beta v1 defaults to the free football provider:

- `DATA_PROVIDER=free`
- `FOOTBALL_DATA_SOURCE=free`
- `FOOTBALL_DATA_SEASON=2026`

The adapter uses ESPN public Site API endpoints for football scoreboards,
summaries and standings. It returns real feed data only. When odds or advanced
statistics are absent from the feed, SportsHunter-AI returns an empty result or
raises the normalized provider exception instead of silently switching to Mock.
