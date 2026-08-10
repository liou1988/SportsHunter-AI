from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from config.settings import Settings, get_settings
from datahub.models import Odds, OddsMarket
from evaluation.dataset import EvaluationDataset
from telegram_bot.localization import translate_league_name

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RecommendationGateDecision:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reasons": self.reasons,
            "metrics": self.metrics,
        }


class RecommendationGate:
    def __init__(
        self,
        settings: Settings | None = None,
        history_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._history_rows = history_rows
        self._league_stats: dict[str, dict[str, float | int]] | None = None

    def evaluate(
        self,
        result: Any,
        odds: list[Odds] | None = None,
        now: datetime | None = None,
    ) -> RecommendationGateDecision:
        if not self.settings.recommendation_gate_enabled:
            return RecommendationGateDecision(passed=True)

        now = _as_utc(now) or datetime.now(timezone.utc)
        reasons: list[str] = []
        metrics: dict[str, Any] = {}

        signal = _result_signal(result)
        allowed_signals = {
            str(item).strip().upper()
            for item in self.settings.recommendation_allowed_signals
            if str(item).strip()
        }
        if signal not in allowed_signals:
            reasons.append("signal_not_actionable")

        score = _safe_float(getattr(getattr(result, "hunter_score", None), "score", None))
        metrics["score"] = score
        if score is None or score < float(self.settings.recommendation_min_score):
            reasons.append("score_below_floor")

        confidence = _safe_float(getattr(getattr(result, "hunter_score", None), "confidence", None))
        metrics["confidence"] = confidence
        if confidence is None or confidence < float(self.settings.recommendation_min_confidence):
            reasons.append("confidence_below_floor")

        risk_level = _risk_level(result)
        metrics["risk_level"] = risk_level
        if risk_level and risk_level != "LOW":
            reasons.append("risk_not_low")

        window = _prematch_window_minutes(getattr(result, "fixture", None), now)
        metrics["prematch_minutes"] = window
        if window is None:
            reasons.append("kickoff_window_invalid")
        elif window < int(self.settings.recommendation_prematch_min_minutes):
            reasons.append("too_close_to_kickoff")
        elif window > int(self.settings.recommendation_prematch_max_minutes):
            reasons.append("too_far_from_kickoff")

        odds_items = odds if odds is not None else _result_odds(result)
        metrics["odds_count"] = len(odds_items)
        if self.settings.recommendation_require_odds and not odds_items:
            reasons.append("odds_missing")

        market_evidence = _market_evidence(result, odds_items)
        metrics["market_evidence"] = market_evidence
        if not _has_required_market_edge(
            market_evidence,
            min_edge=float(self.settings.recommendation_min_market_edge),
            min_expected_value=float(self.settings.recommendation_min_expected_value),
        ):
            reasons.append("market_edge_too_small")

        league_stats = self._league_stats_for_result(result)
        metrics["league_stats"] = league_stats
        if _is_league_underperforming(
            league_stats,
            min_samples=int(self.settings.recommendation_league_min_samples),
            min_hit_rate=float(self.settings.recommendation_league_min_hit_rate),
            min_roi=float(self.settings.recommendation_league_min_roi),
        ):
            reasons.append("league_recent_performance_weak")

        return RecommendationGateDecision(passed=not reasons, reasons=reasons, metrics=metrics)

    def _league_stats_for_result(self, result: Any) -> dict[str, float | int]:
        fixture = getattr(result, "fixture", None)
        league = getattr(fixture, "league", None)
        names = {
            _normal_text(getattr(league, "name", None)),
            _normal_text(translate_league_name(str(getattr(league, "name", "") or ""))),
            _normal_text(getattr(league, "id", None)),
        }
        names.discard("")
        stats = self._league_stats_by_name()
        for name in names:
            if name in stats:
                return stats[name]
        return {"count": 0, "wins": 0, "hit_rate": 0.0, "roi": 0.0}

    def _league_stats_by_name(self) -> dict[str, dict[str, float | int]]:
        if self._league_stats is not None:
            return self._league_stats
        rows = self._history_rows
        if rows is None:
            rows = self._load_history_rows()
            self._history_rows = rows
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            if not row.get("actionable", True):
                continue
            grouped.setdefault(_normal_text(row.get("league")), []).append(row)
        self._league_stats = {
            league: _performance_stats(league_rows)
            for league, league_rows in grouped.items()
            if league
        }
        return self._league_stats

    def _load_history_rows(self) -> list[dict[str, Any]]:
        try:
            return EvaluationDataset().rows_for_days(self.settings.recommendation_league_review_days)
        except Exception as exc:  # noqa: BLE001 - gating should fail open on analytics outages
            logger.warning("recommendation gate history unavailable: %s", exc)
            return []


def _market_evidence(result: Any, odds_items: list[Odds]) -> dict[str, Any]:
    prediction = getattr(result, "market_prediction", None)
    to_dict = getattr(prediction, "to_dict", None)
    payload = to_dict() if callable(to_dict) else (prediction if isinstance(prediction, dict) else {})
    evidence: dict[str, Any] = {
        "moneyline": _moneyline_evidence(payload, odds_items),
        "totals": _line_evidence(payload.get("total_goals") or {}),
        "handicap": _line_evidence(payload.get("handicap") or {}),
    }
    evidence["best_edge"] = max(
        [_safe_abs(item.get("edge")) for item in evidence.values() if isinstance(item, dict)],
        default=0.0,
    )
    evidence["best_expected_value"] = max(
        [
            float(item["expected_value"])
            for item in evidence.values()
            if isinstance(item, dict) and item.get("expected_value") is not None
        ],
        default=None,
    )
    return evidence


def _moneyline_evidence(prediction: dict[str, Any], odds_items: list[Odds]) -> dict[str, Any]:
    pick = str(prediction.get("moneyline_pick") or "").upper()
    probabilities = prediction.get("probabilities") if isinstance(prediction.get("probabilities"), dict) else {}
    model_probability = _safe_float(probabilities.get(pick.lower()))
    european = next((item for item in odds_items if item.market == OddsMarket.EUROPEAN), None)
    market_probability = _moneyline_market_probability(european, pick)
    odds = _moneyline_odds(european, pick)
    expected_value = _expected_value(model_probability, odds)
    edge = (
        model_probability - market_probability
        if model_probability is not None and market_probability is not None
        else None
    )
    return {
        "pick": pick,
        "edge": _round_optional(edge),
        "model_probability": _round_optional(model_probability),
        "market_probability": _round_optional(market_probability),
        "expected_value": expected_value,
        "market_available": european is not None,
    }


def _line_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    pick = str(payload.get("pick") or "").upper()
    if pick in {"", "NO_PLAY"}:
        return {
            "pick": pick or "NO_PLAY",
            "edge": 0.0,
            "expected_value": payload.get("expected_value"),
            "market_available": bool(payload.get("market_available")),
        }
    return {
        "pick": pick,
        "edge": _round_optional(payload.get("edge")),
        "expected_value": _round_optional(payload.get("expected_value")),
        "market_available": bool(payload.get("market_available")),
    }


def _has_required_market_edge(
    evidence: dict[str, Any],
    min_edge: float,
    min_expected_value: float,
) -> bool:
    for item in evidence.values():
        if not isinstance(item, dict) or not item.get("market_available"):
            continue
        expected_value = _safe_float(item.get("expected_value"))
        if expected_value is not None and expected_value >= min_expected_value:
            return True
        edge = _safe_float(item.get("edge"))
        if edge is not None and abs(edge) >= min_edge:
            return True
    return False


def _is_league_underperforming(
    stats: dict[str, float | int],
    min_samples: int,
    min_hit_rate: float,
    min_roi: float,
) -> bool:
    count = int(stats.get("count") or 0)
    if count < min_samples:
        return False
    return float(stats.get("hit_rate") or 0.0) < min_hit_rate or float(stats.get("roi") or 0.0) < min_roi


def _performance_stats(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    count = len(rows)
    wins = sum(1 for row in rows if row.get("won"))
    stake = sum(float(row.get("stake") or 0.0) for row in rows) or 1.0
    profit = sum(float(row.get("profit") or 0.0) for row in rows)
    return {
        "count": count,
        "wins": wins,
        "hit_rate": round(wins / count, 4) if count else 0.0,
        "roi": round(profit / stake, 4),
    }


def _prematch_window_minutes(fixture: Any, now: datetime) -> float | None:
    start_time = _as_utc(getattr(fixture, "start_time", None))
    if start_time is None:
        return None
    status = str(getattr(getattr(fixture, "status", None), "value", getattr(fixture, "status", "")) or "").lower()
    if status not in {"scheduled", "unknown"}:
        return None
    return round((start_time - now).total_seconds() / 60, 2)


def _result_signal(result: Any) -> str:
    signal = getattr(getattr(result, "signal", None), "signal", None)
    return str(getattr(signal, "value", signal) or "").upper()


def _risk_level(result: Any) -> str | None:
    risk = getattr(result, "risk", None)
    level = getattr(risk, "level", None)
    value = getattr(level, "value", level)
    return str(value).upper() if value else None


def _result_odds(result: Any) -> list[Odds]:
    odds = getattr(result, "odds", None)
    return list(odds) if isinstance(odds, list) else []


def _moneyline_market_probability(odds: Odds | None, pick: str) -> float | None:
    if odds is None:
        return None
    probabilities = {
        "HOME": _implied_probability(odds.home),
        "DRAW": _implied_probability(odds.draw),
        "AWAY": _implied_probability(odds.away),
    }
    selected = probabilities.get(pick)
    total = sum(value for value in probabilities.values() if value is not None)
    if selected is None or total <= 0:
        return None
    return selected / total


def _moneyline_odds(odds: Odds | None, pick: str) -> float | None:
    if odds is None:
        return None
    return {
        "HOME": odds.home,
        "DRAW": odds.draw,
        "AWAY": odds.away,
    }.get(pick)


def _expected_value(model_probability: float | None, odds: float | None) -> float | None:
    decimal_odds = _decimal_odds(odds)
    if model_probability is None or decimal_odds is None:
        return None
    return round(model_probability * (decimal_odds - 1) - (1 - model_probability), 4)


def _implied_probability(odds: float | None) -> float | None:
    if odds is None or odds == 0:
        return None
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    if odds >= 100:
        return 100 / (odds + 100)
    return 1 / odds


def _decimal_odds(odds: float | None) -> float | None:
    if odds is None or odds == 0:
        return None
    if odds < 0:
        return 1 + 100 / abs(odds)
    if odds >= 100:
        return 1 + odds / 100
    return odds


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


def _safe_abs(value: object) -> float:
    number = _safe_float(value)
    return abs(number) if number is not None else 0.0


def _round_optional(value: object) -> float | None:
    number = _safe_float(value)
    return round(number, 4) if number is not None else None


def _normal_text(value: object) -> str:
    return str(value or "").casefold().strip()
