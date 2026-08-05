from __future__ import annotations

import httpx

from config.settings import Settings


class HttpJsonClient:
    def __init__(self, settings: Settings, base_url: str, headers: dict[str, str] | None = None) -> None:
        self.settings = settings
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}

    def get_json(self, path: str, params: dict[str, object] | None = None) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        with httpx.Client(timeout=self.settings.provider_timeout_seconds, follow_redirects=True) as client:
            response = client.get(url, params=params, headers=self.headers)
            response.raise_for_status()
            return response.json()
