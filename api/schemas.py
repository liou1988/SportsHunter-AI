from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    app: str
    status: str
    provider: str


class ProviderStatusResponse(BaseModel):
    provider: str
    health: bool
    last_update: str
    latency: float | None
    error: str | None
