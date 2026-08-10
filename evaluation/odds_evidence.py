from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean
from typing import Any


SHARP_BOOKMAKER_KEYWORDS = (
    "pinnacle",
    "betfair",
    "matchbook",
    "sbobet",
    "sbo",
    "singbet",
    "ibc",
)


def summarize_live_odds(
    odds_items: list[Any],
    now: datetime | None = None,
    max_age_minutes: int = 120,
) -> dict[str, Any]:
    now = _as_utc(now) or datetime.now(timezone.utc)
    captured_times = [_as_utc(getattr(item, "captured_at", None)) for item in odds_items]
    captured_times = [item for item in captured_times if item is not None]
    freshest_age = None
    if captured_times:
        freshest = max(captured_times)
        freshest_age = max(0.0, round((now - freshest).total_seconds() / 60, 2))
    bookmakers = sorted({_normal_text(getattr(item, "bookmaker", None)) for item in odds_items})
    bookmakers = [item for item in bookmakers if item]
    markets = sorted({_market_value(getattr(item, "market", None)) for item in odds_items})
    markets = [item for item in markets if item]
    return {
        "bookmaker_count": len(bookmakers),
        "bookmakers": bookmakers[:8],
        "market_count": len(markets),
        "markets": markets,
        "freshest_age_minutes": freshest_age,
        "freshness_bucket": freshness_bucket(freshest_age),
        "stale": freshest_age is None or freshest_age > max_age_minutes,
        "max_age_minutes": max_age_minutes,
        "has_sharp_anchor": any(_is_sharp_bookmaker(item) for item in bookmakers),
    }


def summarize_settled_odds(
    fixture: Any,
    prediction: Any,
    snapshots: list[Any],
) -> dict[str, Any]:
    snapshots = sorted(
        snapshots,
        key=lambda item: _as_utc(getattr(item, "captured_at", None))
        or datetime.min.replace(tzinfo=timezone.utc),
    )
    if not snapshots:
        return empty_settled_odds_context()

    kickoff = _as_utc(getattr(fixture, "start_time", None))
    latest = snapshots[-1]
    latest_captured_at = _as_utc(getattr(latest, "captured_at", None))
    latest_minutes_before_kickoff = _minutes_before(kickoff, latest_captured_at)
    clv_items = _closing_line_value_items(fixture, prediction, snapshots)
    all_clv = [_safe_float(item.get("clv")) for item in clv_items]
    all_clv = [item for item in all_clv if item is not None]
    trusted_clv = [
        float(item["clv"])
        for item in clv_items
        if item.get("trusted") and item.get("clv") is not None
    ]
    return {
        "snapshot_count": len(snapshots),
        "markets": sorted(
            {_market_value(getattr(item, "market", None)) for item in snapshots if getattr(item, "market", None)}
        ),
        "latest_stage": getattr(latest, "stage", None),
        "latest_bookmaker": getattr(latest, "bookmaker", None),
        "minutes_before_kickoff": latest_minutes_before_kickoff,
        "freshness_bucket": freshness_bucket(latest_minutes_before_kickoff),
        "bookmaker_count": len(
            {
                _normal_text(getattr(item, "bookmaker", None))
                for item in snapshots
                if getattr(item, "bookmaker", None)
            }
        ),
        "has_sharp_anchor": any(_is_sharp_bookmaker(getattr(item, "bookmaker", None)) for item in snapshots),
        "has_closing_odds": any(_is_closing_snapshot(fixture, item, include_live=True) for item in snapshots),
        "clv": {
            "items": clv_items,
            "count": len(all_clv),
            "trusted_count": len(trusted_clv),
            "positive_count": sum(1 for item in all_clv if item > 0),
            "positive_rate": round(sum(1 for item in all_clv if item > 0) / len(all_clv), 4)
            if all_clv
            else 0.0,
            "avg": round(mean(all_clv), 4) if all_clv else None,
            "trusted_avg": round(mean(trusted_clv), 4) if trusted_clv else None,
            "best": round(max(all_clv), 4) if all_clv else None,
            "worst": round(min(all_clv), 4) if all_clv else None,
        },
    }


def empty_settled_odds_context() -> dict[str, Any]:
    return {
        "snapshot_count": 0,
        "markets": [],
        "latest_stage": None,
        "latest_bookmaker": None,
        "minutes_before_kickoff": None,
        "freshness_bucket": "missing",
        "bookmaker_count": 0,
        "has_sharp_anchor": False,
        "has_closing_odds": False,
        "clv": {
            "items": [],
            "count": 0,
            "trusted_count": 0,
            "positive_count": 0,
            "positive_rate": 0.0,
            "avg": None,
            "trusted_avg": None,
            "best": None,
            "worst": None,
        },
    }


def freshness_bucket(age_or_minutes_before: float | None) -> str:
    if age_or_minutes_before is None:
        return "missing"
    minutes = abs(float(age_or_minutes_before))
    if minutes <= 30:
        return "0_30"
    if minutes <= 90:
        return "31_90"
    if minutes <= 360:
        return "91_360"
    return "stale"


def _closing_line_value_items(
    fixture: Any,
    prediction: Any,
    snapshots: list[Any],
) -> list[dict[str, Any]]:
    market_prediction = (getattr(prediction, "breakdown_json", None) or {}).get("market_prediction", {})
    prediction_at = _as_utc(getattr(prediction, "created_at", None))
    kickoff = _as_utc(getattr(fixture, "start_time", None))
    items: list[dict[str, Any]] = []

    moneyline_pick = str(market_prediction.get("moneyline_pick") or "").upper()
    if moneyline_pick in {"HOME", "DRAW", "AWAY"}:
        items.append(
            _clv_item(
                market="moneyline",
                pick=moneyline_pick,
                snapshots=snapshots,
                prediction_at=prediction_at,
                kickoff=kickoff,
            )
        )

    totals = market_prediction.get("total_goals") or {}
    total_pick = str(totals.get("pick") or "").upper()
    if total_pick in {"OVER", "UNDER"}:
        items.append(
            _clv_item(
                market="totals",
                pick=total_pick,
                snapshots=snapshots,
                prediction_at=prediction_at,
                kickoff=kickoff,
                entry_odds=_line_payload_odds(totals, total_pick),
                entry_line=_safe_float(totals.get("line")),
                bookmaker=totals.get("bookmaker"),
            )
        )

    handicap = market_prediction.get("handicap") or {}
    handicap_side = str(handicap.get("side") or "").lower()
    if handicap_side in {"home", "away"}:
        items.append(
            _clv_item(
                market="handicap",
                pick=handicap_side.upper(),
                side=handicap_side,
                snapshots=snapshots,
                prediction_at=prediction_at,
                kickoff=kickoff,
                entry_odds=_handicap_payload_odds(handicap, handicap_side),
                entry_line=_safe_float(handicap.get("line")),
                bookmaker=handicap.get("bookmaker"),
            )
        )

    return [item for item in items if item.get("entry_odds") is not None or item.get("close_odds") is not None]


def _clv_item(
    market: str,
    pick: str,
    snapshots: list[Any],
    prediction_at: datetime | None,
    kickoff: datetime | None,
    side: str | None = None,
    entry_odds: float | None = None,
    entry_line: float | None = None,
    bookmaker: str | None = None,
) -> dict[str, Any]:
    entry_snapshot = _entry_snapshot(
        snapshots,
        market=market,
        pick=pick,
        side=side,
        line=entry_line,
        bookmaker=bookmaker,
        prediction_at=prediction_at,
    )
    if entry_odds is None and entry_snapshot is not None:
        entry_odds = _snapshot_pick_odds(entry_snapshot, market, pick, side)
    if entry_line is None and entry_snapshot is not None:
        entry_line = _selected_line(entry_snapshot, market, side)

    close_snapshot = _closing_snapshot(
        snapshots,
        fixture_kickoff=kickoff,
        market=market,
        pick=pick,
        side=side,
        line=entry_line,
        bookmaker=bookmaker,
        require_same_line=True,
    )
    close_odds = _snapshot_pick_odds(close_snapshot, market, pick, side) if close_snapshot is not None else None

    line_snapshot = close_snapshot or _closing_snapshot(
        snapshots,
        fixture_kickoff=kickoff,
        market=market,
        pick=pick,
        side=side,
        line=entry_line,
        bookmaker=bookmaker,
        require_same_line=False,
    )
    close_line = _selected_line(line_snapshot, market, side) if line_snapshot is not None else None
    clv = _odds_clv(entry_odds, close_odds)
    close_captured_at = _as_utc(getattr(close_snapshot, "captured_at", None)) if close_snapshot is not None else None
    return {
        "market": market,
        "pick": pick,
        "entry_odds": _round_optional(entry_odds),
        "close_odds": _round_optional(close_odds),
        "clv": clv,
        "positive": clv is not None and clv > 0,
        "entry_line": _round_optional(entry_line),
        "close_line": _round_optional(close_line),
        "line_move": _line_move(entry_line, close_line),
        "entry_bookmaker": bookmaker or getattr(entry_snapshot, "bookmaker", None),
        "close_bookmaker": getattr(close_snapshot, "bookmaker", None) if close_snapshot is not None else None,
        "close_stage": getattr(close_snapshot, "stage", None) if close_snapshot is not None else None,
        "close_minutes_before_kickoff": _minutes_before(kickoff, close_captured_at),
        "trusted": close_snapshot is not None and _is_closing_snapshot_time(kickoff, close_captured_at),
    }


def _entry_snapshot(
    snapshots: list[Any],
    market: str,
    pick: str,
    side: str | None,
    line: float | None,
    bookmaker: str | None,
    prediction_at: datetime | None,
) -> Any | None:
    candidates = [
        item
        for item in snapshots
        if _snapshot_matches(item, market, pick, side, line, require_same_line=line is not None)
        and _snapshot_pick_odds(item, market, pick, side) is not None
    ]
    if not candidates:
        return None
    same_book = [item for item in candidates if _same_bookmaker(item, bookmaker)]
    pool = same_book or candidates
    if prediction_at is None:
        return sorted(pool, key=lambda item: _as_utc(getattr(item, "captured_at", None)) or datetime.min.replace(tzinfo=timezone.utc))[-1]
    return min(
        pool,
        key=lambda item: abs(
            ((_as_utc(getattr(item, "captured_at", None)) or prediction_at) - prediction_at).total_seconds()
        ),
    )


def _closing_snapshot(
    snapshots: list[Any],
    fixture_kickoff: datetime | None,
    market: str,
    pick: str,
    side: str | None,
    line: float | None,
    bookmaker: str | None,
    require_same_line: bool,
) -> Any | None:
    candidates = [
        item
        for item in snapshots
        if _snapshot_matches(item, market, pick, side, line, require_same_line=require_same_line)
        and _snapshot_pick_odds(item, market, pick, side) is not None
        and _is_before_kickoff(item, fixture_kickoff)
    ]
    if not candidates:
        return None
    closing = [item for item in candidates if _is_closing_snapshot_time(fixture_kickoff, _as_utc(getattr(item, "captured_at", None)))]
    pool = closing or candidates
    same_book = [item for item in pool if _same_bookmaker(item, bookmaker)]
    pool = same_book or pool
    return sorted(pool, key=lambda item: _as_utc(getattr(item, "captured_at", None)) or datetime.min.replace(tzinfo=timezone.utc))[-1]


def _snapshot_matches(
    snapshot: Any,
    market: str,
    pick: str,
    side: str | None,
    line: float | None,
    require_same_line: bool,
) -> bool:
    if _market_value(getattr(snapshot, "market", None)) != _snapshot_market(market):
        return False
    if require_same_line and line is not None:
        selected_line = _selected_line(snapshot, market, side)
        if selected_line is None or abs(selected_line - line) > 0.01:
            return False
    return _snapshot_pick_odds(snapshot, market, pick, side) is not None


def _snapshot_market(market: str) -> str:
    return {
        "moneyline": "european",
        "totals": "totals",
        "handicap": "asian_handicap",
    }.get(market, market)


def _snapshot_pick_odds(snapshot: Any | None, market: str, pick: str, side: str | None = None) -> float | None:
    if snapshot is None:
        return None
    pick = pick.upper()
    if market == "moneyline":
        return _safe_float({"HOME": getattr(snapshot, "home", None), "DRAW": getattr(snapshot, "draw", None), "AWAY": getattr(snapshot, "away", None)}.get(pick))
    if market == "totals":
        return _safe_float({"OVER": getattr(snapshot, "over", None), "UNDER": getattr(snapshot, "under", None)}.get(pick))
    if market == "handicap":
        return _safe_float(getattr(snapshot, "home", None) if side == "home" else getattr(snapshot, "away", None))
    return None


def _selected_line(snapshot: Any | None, market: str, side: str | None = None) -> float | None:
    if snapshot is None:
        return None
    line = _safe_float(getattr(snapshot, "line", None))
    if line is None:
        return None
    if market == "handicap" and side == "away":
        return -line
    return line


def _line_payload_odds(payload: dict[str, Any], pick: str) -> float | None:
    if pick == "OVER":
        return _safe_float(payload.get("over_odds"))
    if pick == "UNDER":
        return _safe_float(payload.get("under_odds"))
    return None


def _handicap_payload_odds(payload: dict[str, Any], side: str) -> float | None:
    if side == "home":
        return _safe_float(payload.get("home_odds"))
    if side == "away":
        return _safe_float(payload.get("away_odds"))
    return None


def _is_closing_snapshot(fixture: Any, snapshot: Any, include_live: bool = False) -> bool:
    stage = str(getattr(snapshot, "stage", "") or "").lower()
    if stage == "closing" or (include_live and stage == "live"):
        return True
    return _is_closing_snapshot_time(
        _as_utc(getattr(fixture, "start_time", None)),
        _as_utc(getattr(snapshot, "captured_at", None)),
    )


def _is_closing_snapshot_time(kickoff: datetime | None, captured_at: datetime | None) -> bool:
    minutes = _minutes_before(kickoff, captured_at)
    return minutes is not None and 0 <= minutes <= 90


def _is_before_kickoff(snapshot: Any, kickoff: datetime | None) -> bool:
    captured_at = _as_utc(getattr(snapshot, "captured_at", None))
    return kickoff is None or captured_at is None or captured_at <= kickoff


def _minutes_before(kickoff: datetime | None, captured_at: datetime | None) -> float | None:
    if kickoff is None or captured_at is None:
        return None
    return round((kickoff - captured_at).total_seconds() / 60, 2)


def _odds_clv(entry_odds: float | None, close_odds: float | None) -> float | None:
    entry = _decimal_odds(entry_odds)
    close = _decimal_odds(close_odds)
    if entry is None or close is None or close <= 1:
        return None
    return round(entry / close - 1, 4)


def _line_move(entry_line: float | None, close_line: float | None) -> float | None:
    if entry_line is None or close_line is None:
        return None
    return round(entry_line - close_line, 4)


def _decimal_odds(odds: float | None) -> float | None:
    if odds is None or odds == 0:
        return None
    if odds < 0:
        return 1 + 100 / abs(odds)
    if odds >= 100:
        return 1 + odds / 100
    return odds


def _is_sharp_bookmaker(bookmaker: object) -> bool:
    normalized = _normal_text(bookmaker)
    return any(keyword in normalized for keyword in SHARP_BOOKMAKER_KEYWORDS)


def _same_bookmaker(snapshot: Any, bookmaker: object) -> bool:
    expected = _normal_text(bookmaker)
    return bool(expected) and _normal_text(getattr(snapshot, "bookmaker", None)) == expected


def _market_value(value: object) -> str:
    return str(getattr(value, "value", value) or "")


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _safe_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_optional(value: object) -> float | None:
    number = _safe_float(value)
    return round(number, 4) if number is not None else None


def _normal_text(value: object) -> str:
    return str(value or "").casefold().strip()
