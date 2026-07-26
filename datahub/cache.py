from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Callable, Generic, TypeVar


T = TypeVar("T")


@dataclass
class CacheEntry(Generic[T]):
    value: T
    expires_at: float


class TTLCache:
    def __init__(self, default_ttl_seconds: int = 180) -> None:
        self.default_ttl_seconds = default_ttl_seconds
        self._items: dict[str, CacheEntry[object]] = {}

    def get(self, key: str) -> object | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        if entry.expires_at <= monotonic():
            self._items.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: object, ttl_seconds: int | None = None) -> object:
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        self._items[key] = CacheEntry(value=value, expires_at=monotonic() + ttl)
        return value

    def get_or_set(self, key: str, factory: Callable[[], T], ttl_seconds: int | None = None) -> T:
        cached = self.get(key)
        if cached is not None:
            return cached  # type: ignore[return-value]
        value = factory()
        self.set(key, value, ttl_seconds)
        return value

    def clear(self) -> None:
        self._items.clear()
