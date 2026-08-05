from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


BEIJING_TZ = ZoneInfo("Asia/Shanghai")
PRE_MATCH_FIXTURE_STATUSES = {"scheduled", "unknown"}
LIVE_FIXTURE_STATUSES = {"live"}
LIVE_FIXTURE_MAX_AGE = timedelta(hours=3)


def prediction_candidate_fixtures(
    today_fixtures: list[Any],
    live_fixtures: list[Any] | None = None,
    now: datetime | None = None,
) -> list[Any]:
    now = _as_utc(now) or datetime.now(timezone.utc)
    candidates: list[Any] = []
    seen: set[tuple[str, str]] = set()
    for fixture in [*today_fixtures, *(live_fixtures or [])]:
        if not is_prediction_candidate_fixture(fixture, now):
            continue
        key = _fixture_key(fixture)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(fixture)
    return candidates


def is_prediction_candidate_fixture(fixture: Any, now: datetime | None = None) -> bool:
    if fixture is None:
        return False

    start_time = _as_utc(getattr(fixture, "start_time", None))
    if start_time is None:
        return False

    now = _as_utc(now) or datetime.now(timezone.utc)
    if not _is_beijing_today(start_time, now):
        return False

    status = _fixture_status_value(fixture)
    if status in PRE_MATCH_FIXTURE_STATUSES:
        return start_time >= now
    if status in LIVE_FIXTURE_STATUSES:
        return start_time <= now and now - start_time <= LIVE_FIXTURE_MAX_AGE
    return False


def _fixture_status_value(fixture: Any) -> str:
    raw_status = getattr(fixture, "status", "unknown") or "unknown"
    return str(getattr(raw_status, "value", raw_status)).lower()


def _fixture_key(fixture: Any) -> tuple[str, str]:
    return (
        str(getattr(fixture, "provider", "") or ""),
        str(getattr(fixture, "id", "") or ""),
    )


def _is_beijing_today(start_time: datetime, now: datetime) -> bool:
    return start_time.astimezone(BEIJING_TZ).date() == now.astimezone(BEIJING_TZ).date()


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
