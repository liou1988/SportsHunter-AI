from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> str:
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SportsHunter-AI Dashboard</title>
  <link rel="stylesheet" href="/dashboard/static/styles.css">
</head>
<body>
  <main class="shell">
    <header>
      <h1>SportsHunter-AI</h1>
      <p>Beta v1 prediction operations dashboard</p>
    </header>
    <section class="grid">
      <a href="/api/health">API Health</a>
      <a href="/provider/status">Provider Status</a>
      <a href="/api/matches/today">Today Matches</a>
      <a href="/api/predictions/today">Predictions</a>
    </section>
  </main>
</body>
</html>
"""
