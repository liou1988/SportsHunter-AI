from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, TypeVar

from config.settings import Settings
from datahub.cache import TTLCache
from datahub.models import Fixture, Odds, Standing, Statistics

logger = logging.getLogger(__name__)
T = TypeVar("T")


class ProviderUnavailableError(RuntimeError):
    def __init__(self, provider: str, message: str) -> None:
        self.provider = provider
        super().__init__(f"{provider}: {message}")


@dataclass(slots=True)
class ProviderHealth:
    provider: str
    health: bool
    last_update: datetime
    latency: float | None = None
    error: str | None = None


class BaseProvider(ABC):
    name = "base"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.cache = TTLCache(settings.provider_cache_ttl_seconds)
        self.last_health: ProviderHealth | None = None

    def cached(self, key: str, factory: Callable[[], T], ttl_seconds: int | None = None) -> T:
        return self.cache.get_or_set(f"{self.name}:{key}", factory, ttl_seconds)

    def retry(self, operation: str, func: Callable[[], T]) -> T:
        attempts = max(1, self.settings.provider_retry_attempts)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return func()
            except Exception as exc:  # noqa: BLE001 - provider boundary normalizes errors
                last_error = exc
                logger.warning(
                    "provider operation failed",
                    extra={"provider": self.name, "operation": operation, "attempt": attempt},
                    exc_info=exc,
                )
                if attempt < attempts:
                    time.sleep(self.settings.provider_retry_backoff_seconds * attempt)
        raise ProviderUnavailableError(self.name, f"{operation} failed: {last_error}") from last_error

    def health_check(self) -> ProviderHealth:
        started = time.perf_counter()
        try:
            self.get_today_fixtures()
            health = ProviderHealth(
                provider=self.name,
                health=True,
                last_update=datetime.now(timezone.utc),
                latency=round(time.perf_counter() - started, 3),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("provider health check failed", extra={"provider": self.name}, exc_info=exc)
            health = ProviderHealth(
                provider=self.name,
                health=False,
                last_update=datetime.now(timezone.utc),
                latency=round(time.perf_counter() - started, 3),
                error=str(exc),
            )
        self.last_health = health
        return health

    @abstractmethod
    def get_today_fixtures(self) -> list[Fixture]:
        raise NotImplementedError

    @abstractmethod
    def get_fixture(self, fixture_id: str) -> Fixture:
        raise NotImplementedError

    @abstractmethod
    def get_live_matches(self) -> list[Fixture]:
        raise NotImplementedError

    @abstractmethod
    def get_odds(self, fixture_id: str) -> list[Odds]:
        raise NotImplementedError

    @abstractmethod
    def get_statistics(self, fixture_id: str) -> Statistics:
        raise NotImplementedError

    @abstractmethod
    def get_standings(self, league: str) -> list[Standing]:
        raise NotImplementedError
