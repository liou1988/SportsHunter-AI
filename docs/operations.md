# Operations

Start the full API service:

```bash
docker compose up -d --build
```

Useful endpoints:

- `GET /api/health`
- `GET /provider/status`
- `GET /api/provider/debug`
- `GET /api/matches/today`
- `GET /api/predictions/today`
- `POST /api/telegram/alerts/check`
- `GET /api/recommendations/today`
- `GET /api/recommendations/archive`
- `GET /dashboard`
- `GET /api/dashboard/summary`
- `POST /api/dashboard/data-quality/check`
- `POST /api/dashboard/evaluation/run`

Prediction/evaluation loop:

- Today recommendations are archived to `predictions` with deduped snapshots.
- Successful Telegram alerts also archive the delivered prediction snapshot.
- Finished fixtures are settled to `match_results` by the post-match collector.
- The post-match collector scans recent archived predictions that are still unsettled.
- SQLite runs with WAL mode, a 30 second busy timeout and per-fixture commits
  during sync to reduce write-lock contention between scheduled jobs.
- Evaluation creates `learning_records` and writes `reports/daily_report.md`.
- The model optimizer check writes `reports/model_optimizer_status.json` and
  auto-applies weight suggestions by default once at least
  `MODEL_OPTIMIZER_AUTO_APPLY_MIN_SAMPLES=100` settled samples are available.
  Set `MODEL_OPTIMIZER_AUTO_APPLY_ENABLED=false` to require Dashboard/manual
  review before applying weights.

Default automation schedule, Asia/Shanghai:

- `06:00` sync today fixtures.
- `08:00` update odds.
- `08:10` archive today's prediction snapshots.
- Every `5` minutes refresh live fixtures and check Telegram recommendation alerts.
- `23:30` save results and settle recent archived predictions.
- `01:00` generate the daily review report.
- `01:20` check model optimizer suggestions and auto-apply when the configured
  sample gate is reached.

Manual report generation inside the API container:

```bash
docker exec sportshunter-ai-api python -c "from evaluation.runner import EvaluationRunner; print(EvaluationRunner().daily().to_markdown())"
```

Manual DataHub quality check:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/dashboard/data-quality/check | python3 -m json.tool
```

The quality payload includes checked sources, checked/skipped leagues, fixture
counts per league, sample odds coverage for European odds, totals and Asian
handicap, and fixture-level errors.

Generated runtime files such as SQLite databases, logs, reports and validation
reports are excluded from Git.
