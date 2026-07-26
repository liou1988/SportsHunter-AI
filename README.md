# SportsHunter-AI

SportsHunter-AI is a professional sports match prediction system built with
FastAPI, SQLAlchemy, Alembic, APScheduler, Provider-based data collection,
rule-based Hunter Rating, Risk, Signal, Evaluation, and Automation engines.

Beta v1.0.1 requires **Python >=3.12** and defaults to a multi-source free
football provider.

## Docker one-command deploy

```bash
docker compose up -d --build
```

Open:

- API health: http://localhost:8000/api/health
- Swagger: http://localhost:8000/docs
- Dashboard: http://localhost:8000/dashboard
- Provider status: http://localhost:8000/provider/status

Docker runs Alembic migrations automatically and stores SQLite data in a Docker
volume.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m alembic upgrade head
python -m scripts.run_api
```

Run tests:

```bash
pytest
```

## Default provider

`.env.example` defaults:

```env
DATA_PROVIDER=free
FOOTBALL_DATA_SOURCE=free
FOOTBALL_DATA_SEASON=2026
```

The free provider returns real football fixtures, live scores and basic
statistics when available. It combines ESPN public football feeds with
TheSportsDB's free day-event feed, aggregates all configured leagues, de-duplicates
cross-source matches, and does not fake unavailable odds.

Useful provider controls:

```env
FREE_PROVIDER_SOURCES=espn,thesportsdb
FREE_PROVIDER_FOOTBALL_LEAGUES=eng.1,eng.2,esp.1,ger.1,bra.2,arg.2,club.friendly,...
```

Provider diagnostics:

- `GET /api/provider/debug` shows checked sources, league counts, skipped ESPN
  slugs, raw fixture count and parsed fixture count.

## Telegram alerts

Telegram recommendations are event-style alerts now: SportsHunter-AI checks the
prediction pipeline every few minutes and sends a message only when a new
qualified match appears. There is no fixed daily recommendation push.

```env
TELEGRAM_PUSH_ENABLED=true
TELEGRAM_ALERT_SIGNALS=STRONG_BUY,BUY
TELEGRAM_ALERT_INTERVAL_MINUTES=5
```

Manual alert check:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/telegram/alerts/check | python3 -m json.tool
```

## Directories

```text
api/             FastAPI routers and schemas
backend/         FastAPI app entrypoint
automation/      Daily automation runner, scheduler, health check and watchdog
backtest/        Backtesting helpers
collector/       Append-only historical snapshots
config/          Settings and logging
core/            Hunter Rating, Risk and Signal engines
crawler/         Scanner abstractions
database/        SQLAlchemy ORM, repositories and Alembic migrations
datahub/         Unified Provider interface, cache and data models
data_sync/       Daily/live sync
docs/            Documentation
evaluation/      Prediction-vs-result evaluation reports
features/        Feature Engine
free_provider/   Free football provider adapter
pipeline/        End-to-end PredictionPipeline
providers/       Real provider placeholders
scheduler/       APScheduler jobs
telegram_bot/    Telegram notifier
tests/           Automated tests
validation/      Full-chain validation runner
```
