# Automation Runner

The scheduler registers the Beta v1 operating cycle:

- 06:00 sync today's fixtures
- 08:00 update odds
- every 5 minutes refresh live matches
- every 5 minutes check recommendations and immediately push newly qualified Telegram alerts
- 23:30 save post-match results
- 01:00 generate the daily report
- every 10 minutes write `system_status.md`

Telegram recommendations are no longer pushed as a fixed 08:00 batch. The
alert job evaluates the current prediction pipeline and sends only new
`STRONG_BUY` / `BUY` / `WATCH` matches that have not been pushed before.

Provider, scheduler, database, prediction and evaluation status are exposed
through the health modules and provider status API.
