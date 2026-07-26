# SportsHunter-AI

SportsHunter-AI is a professional sports match prediction system built with
FastAPI, SQLAlchemy, Alembic, APScheduler, Provider-based data collection,
rule-based Hunter Rating, Risk, Signal, Evaluation, and Automation engines.

Beta v1.0.1 requires **Python >=3.12** and defaults to the free ESPN public
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
statistics when available. It does not fake unavailable odds.

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
