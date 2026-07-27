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
- `GET /dashboard`
- `GET /api/dashboard/summary`
- `POST /api/dashboard/data-quality/check`
- `POST /api/dashboard/evaluation/run`

Prediction/evaluation loop:

- Successful Telegram alerts are saved to `predictions`.
- Finished fixtures are settled to `match_results` by the post-match collector.
- Evaluation creates `learning_records` and writes `reports/daily_report.md`.

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
