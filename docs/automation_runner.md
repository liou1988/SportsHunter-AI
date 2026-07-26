# Automation Runner

The scheduler registers the Beta v1 operating cycle:

- 06:00 sync today's fixtures
- 08:00 update odds
- every 5 minutes refresh live matches
- 23:30 save post-match results
- 01:00 generate the daily report
- every 10 minutes write `system_status.md`

Provider, scheduler, database, prediction and evaluation status are exposed
through the health modules and provider status API.
