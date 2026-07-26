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
- `GET /dashboard`

Generated runtime files such as SQLite databases, logs, reports and validation
reports are excluded from Git.
