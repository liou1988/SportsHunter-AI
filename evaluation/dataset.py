from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from database import models as orm
from database.repositories import SportsRepository
from database.session import SessionLocal
from evaluation.odds_evidence import empty_settled_odds_context, summarize_settled_odds
from telegram_bot.localization import translate_league_name, translate_match_text

SessionFactory = Callable[[], Session]

PERIOD_DAYS = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
}


class _OddsSnapshotContext(NamedTuple):
    fixture_id: int
    provider: str | None
    market: str | None
    line: float | None
    home: float | None
    draw: float | None
    away: float | None
    over: float | None
    under: float | None
    stage: str | None
    bookmaker: str | None
    captured_at: datetime | None


class EvaluationDataset:
    def __init__(self, session_factory: SessionFactory = SessionLocal) -> None:
        self.session_factory = session_factory

    def rows(self, period: str = "daily") -> list[dict]:
        return self.rows_for_days(PERIOD_DAYS.get(period, 1))

    def rows_for_days(self, days: int) -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
        with self.session_factory() as session:
            repo = SportsRepository(session)
            settled = repo.settled_predictions(since=since)
            latest_settled = _latest_prediction_per_fixture(settled)
            fixtures_by_id = {fixture.id: fixture for _, fixture, _ in latest_settled}
            predictions_by_fixture_id = {fixture.id: prediction for prediction, fixture, _ in latest_settled}
            odds_contexts = _odds_contexts_for_fixtures(
                session,
                fixtures_by_id,
                predictions_by_fixture_id,
            )
            return [
                _build_row(
                    prediction,
                    fixture,
                    result,
                    odds_contexts.get(fixture.id, _empty_odds_context()),
                )
                for prediction, fixture, result in latest_settled
            ]

    def create_learning_records(self, rows: list[dict]) -> int:
        created = 0
        with self.session_factory() as session:
            repo = SportsRepository(session)
            for row in rows:
                prediction_id = row.get("prediction_id")
                if not prediction_id or repo.learning_record_exists(int(prediction_id)):
                    continue
                prediction = session.get(orm.Prediction, int(prediction_id))
                if prediction is None:
                    continue
                repo.add_learning_record(
                    prediction=prediction,
                    outcome="win" if row.get("won") else "loss",
                    module=row.get("primary_error_module"),
                    adjustment={
                        "score_error": row.get("score_error"),
                        "total_goals_hit": row.get("total_goals_hit"),
                        "handicap_hit": row.get("handicap_hit"),
                        "hunter_score": row.get("hunter_score"),
                        "confidence": row.get("confidence"),
                    },
                    notes=_learning_note(row),
                )
                created += 1
            session.commit()
        return created


def _latest_prediction_per_fixture(
    settled: list[tuple[orm.Prediction, orm.Fixture, orm.MatchResult]],
) -> list[tuple[orm.Prediction, orm.Fixture, orm.MatchResult]]:
    latest: list[tuple[orm.Prediction, orm.Fixture, orm.MatchResult]] = []
    seen_fixture_ids: set[int] = set()
    for prediction, fixture, result in settled:
        if fixture.id in seen_fixture_ids:
            continue
        seen_fixture_ids.add(fixture.id)
        latest.append((prediction, fixture, result))
    return latest


def _build_row(
    prediction: orm.Prediction,
    fixture: orm.Fixture,
    result: orm.MatchResult,
    odds_context: dict[str, Any] | None = None,
) -> dict:
    market_prediction = (prediction.breakdown_json or {}).get("market_prediction", {})
    score_prediction = market_prediction.get("score", {})
    total_goals = market_prediction.get("total_goals", {})
    handicap = market_prediction.get("handicap", {})
    odds_context = odds_context or _empty_odds_context()
    clv_context = odds_context.get("clv") or {}
    winner_side = _winner_side(result.home_score, result.away_score)
    moneyline_pick = str(market_prediction.get("moneyline_pick") or "").upper()
    won = _moneyline_hit(moneyline_pick, prediction.predicted_side, fixture, winner_side)
    stake = float(prediction.stake or 0.0)
    actionable = stake > 0 and prediction.signal not in {"PASS", "BLOCK"}

    row = {
        "prediction_id": prediction.id,
        "fixture_id": fixture.id,
        "league": translate_league_name(fixture.league.name if fixture.league else "unknown"),
        "fixture": translate_match_text(f"{fixture.home_team.name} vs {fixture.away_team.name}"),
        "signal": prediction.signal,
        "stake": stake,
        "hunter_score": prediction.hunter_score,
        "confidence": prediction.confidence,
        "risk_level": prediction.risk_level,
        "risk_score": prediction.risk_score,
        "home_score": result.home_score,
        "away_score": result.away_score,
        "winner": winner_side,
        "moneyline_pick": moneyline_pick,
        "predicted_score": _predicted_score_text(score_prediction),
        "predicted_home_score": score_prediction.get("home"),
        "predicted_away_score": score_prediction.get("away"),
        "total_goals_label": total_goals.get("label"),
        "total_goals_pick": total_goals.get("pick"),
        "total_goals_line": total_goals.get("line"),
        "handicap_label": handicap.get("label"),
        "handicap_side": handicap.get("side"),
        "handicap_line": handicap.get("line"),
        "odds_snapshot_count": odds_context["snapshot_count"],
        "odds_markets": odds_context["markets"],
        "latest_odds_stage": odds_context["latest_stage"],
        "latest_odds_bookmaker": odds_context["latest_bookmaker"],
        "latest_odds_minutes_before_kickoff": odds_context["minutes_before_kickoff"],
        "odds_freshness_bucket": odds_context.get("freshness_bucket"),
        "odds_bookmaker_count": odds_context.get("bookmaker_count", 0),
        "has_sharp_anchor": odds_context.get("has_sharp_anchor", False),
        "has_closing_odds": odds_context["has_closing_odds"],
        "clv": clv_context,
        "avg_clv": clv_context.get("avg"),
        "trusted_clv": clv_context.get("trusted_avg"),
        "positive_clv_rate": clv_context.get("positive_rate", 0.0),
        "won": won if actionable else False,
        "actionable": actionable,
        "profit": _profit(stake, won) if actionable else 0.0,
        "score_error": _score_error(score_prediction, result.home_score, result.away_score),
        "total_goals_hit": _total_goals_hit(total_goals, result.home_score, result.away_score),
        "handicap_hit": _handicap_hit(handicap, result.home_score, result.away_score),
    }
    row["market_results"] = {
        "moneyline": row["won"] if actionable else None,
        "totals": row["total_goals_hit"],
        "handicap": row["handicap_hit"],
    }
    row["primary_error_module"] = _primary_error_module(row, prediction.breakdown_json or {})
    return row


def _odds_contexts_for_fixtures(
    session: Session,
    fixtures_by_id: dict[int, orm.Fixture],
    predictions_by_fixture_id: dict[int, orm.Prediction],
) -> dict[int, dict[str, Any]]:
    if not fixtures_by_id:
        return {}
    snapshots = session.execute(
        select(
            orm.OddsSnapshot.fixture_id,
            orm.OddsSnapshot.provider,
            orm.OddsSnapshot.market,
            orm.OddsSnapshot.line,
            orm.OddsSnapshot.home,
            orm.OddsSnapshot.draw,
            orm.OddsSnapshot.away,
            orm.OddsSnapshot.over,
            orm.OddsSnapshot.under,
            orm.OddsSnapshot.stage,
            orm.OddsSnapshot.bookmaker,
            orm.OddsSnapshot.captured_at,
        )
        .where(orm.OddsSnapshot.fixture_id.in_(list(fixtures_by_id)))
        .order_by(orm.OddsSnapshot.fixture_id.asc(), orm.OddsSnapshot.captured_at.asc())
    )
    grouped: dict[int, list[_OddsSnapshotContext]] = {fixture_id: [] for fixture_id in fixtures_by_id}
    for fixture_id, provider, market, line, home, draw, away, over, under, stage, bookmaker, captured_at in snapshots:
        grouped.setdefault(fixture_id, []).append(
            _OddsSnapshotContext(
                fixture_id=fixture_id,
                provider=provider,
                market=market,
                line=line,
                home=home,
                draw=draw,
                away=away,
                over=over,
                under=under,
                stage=stage,
                bookmaker=bookmaker,
                captured_at=captured_at,
            )
        )
    return {
        fixture_id: summarize_settled_odds(
            fixtures_by_id[fixture_id],
            predictions_by_fixture_id[fixture_id],
            fixture_snapshots,
        )
        for fixture_id, fixture_snapshots in grouped.items()
    }


def _empty_odds_context() -> dict[str, Any]:
    return empty_settled_odds_context()


def _moneyline_hit(moneyline_pick: str, predicted_side: str | None, fixture: orm.Fixture, winner_side: str | None) -> bool:
    if winner_side is None:
        return False
    if moneyline_pick == "DRAW":
        return winner_side == "draw"
    if winner_side == "home":
        return predicted_side == fixture.home_team.name or moneyline_pick == "HOME"
    if winner_side == "away":
        return predicted_side == fixture.away_team.name or moneyline_pick == "AWAY"
    return False


def _score_error(score_prediction: dict[str, Any], home_score: int | None, away_score: int | None) -> int | None:
    if home_score is None or away_score is None:
        return None
    predicted_home = score_prediction.get("home")
    predicted_away = score_prediction.get("away")
    if predicted_home is None or predicted_away is None:
        return None
    return abs(int(predicted_home) - home_score) + abs(int(predicted_away) - away_score)


def _predicted_score_text(score_prediction: dict[str, Any]) -> str:
    text = score_prediction.get("text")
    if text:
        return str(text)
    predicted_home = score_prediction.get("home")
    predicted_away = score_prediction.get("away")
    if predicted_home is None or predicted_away is None:
        return "-"
    return f"{predicted_home}-{predicted_away}"


def _total_goals_hit(total_goals: dict[str, Any], home_score: int | None, away_score: int | None) -> bool | None:
    pick = str(total_goals.get("pick") or "").upper()
    line = total_goals.get("line")
    if pick not in {"OVER", "UNDER"} or line is None or home_score is None or away_score is None:
        return None
    actual_total = home_score + away_score
    if pick == "OVER":
        return actual_total > float(line)
    return actual_total < float(line)


def _handicap_hit(handicap: dict[str, Any], home_score: int | None, away_score: int | None) -> bool | None:
    side = str(handicap.get("side") or "").lower()
    line = handicap.get("line")
    if side not in {"home", "away"} or line is None or home_score is None or away_score is None:
        return None
    if side == "home":
        adjusted_margin = home_score + float(line) - away_score
    else:
        adjusted_margin = away_score + float(line) - home_score
    if adjusted_margin == 0:
        return None
    return adjusted_margin > 0


def _winner_side(home_score: int | None, away_score: int | None) -> str | None:
    if home_score is None or away_score is None:
        return None
    if home_score > away_score:
        return "home"
    if away_score > home_score:
        return "away"
    return "draw"


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _profit(stake: float, won: bool) -> float:
    return stake if won else -stake


def _primary_error_module(row: dict, breakdown_json: dict) -> str | None:
    if row.get("won"):
        return "aligned_signal"
    if row.get("score_error") is not None and row["score_error"] >= 3:
        return "score_projection"
    if row.get("total_goals_hit") is False:
        return "totals_market"
    if row.get("handicap_hit") is False:
        return "handicap_market"
    modules = ((breakdown_json.get("hunter_score") or {}).get("breakdown") or {}).get("modules", {})
    if modules:
        return max(modules, key=modules.get)
    return "signal"


def _learning_note(row: dict) -> str:
    if row.get("won"):
        return (
            "\u63a8\u8350\u65b9\u5411\u547d\u4e2d\uff0c\u5f53\u524d\u8bc4\u5206\u3001\u98ce\u9669\u548c\u5e02\u573a\u4fe1\u53f7\u4fdd\u6301\u4e00\u81f4\uff1b"
            f"\u9884\u6d4b\u6bd4\u5206 {row.get('predicted_score')}\uff0c\u5b9e\u9645\u6bd4\u5206 {_result_score(row)}\uff0c"
            f"\u6bd4\u5206\u8bef\u5dee {row.get('score_error')}\uff0c\u5927\u5c0f\u7403 {_hit_label(row.get('total_goals_hit'))}\uff0c"
            f"\u8ba9\u7403 {_hit_label(row.get('handicap_hit'))}\u3002"
        )
    module = row.get("primary_error_module") or "unknown"
    return (
        f"\u63a8\u8350\u672a\u547d\u4e2d\uff0c\u9700\u8981\u590d\u6838 {_learning_module_label(module)}\uff1b"
        f"\u9884\u6d4b\u6bd4\u5206 {row.get('predicted_score')}\uff0c\u5b9e\u9645\u6bd4\u5206 {_result_score(row)}\uff0c"
        f"\u6bd4\u5206\u8bef\u5dee {row.get('score_error')}\uff0c\u5927\u5c0f\u7403 {_hit_label(row.get('total_goals_hit'))}\uff0c"
        f"\u8ba9\u7403 {_hit_label(row.get('handicap_hit'))}\u3002"
    )


def _result_score(row: dict) -> str:
    home_score = row.get("home_score")
    away_score = row.get("away_score")
    if home_score is None or away_score is None:
        return "-"
    return f"{home_score}-{away_score}"



def _hit_label(value: object) -> str:
    if value is True:
        return "\u547d\u4e2d"
    if value is False:
        return "\u672a\u4e2d"
    return "\u672a\u8bc4\u4f30"


def _learning_module_label(module: str) -> str:
    return {
        "aligned_signal": "\u4fe1\u53f7\u4e00\u81f4\u6027",
        "score_projection": "\u6bd4\u5206\u9884\u6d4b",
        "totals_market": "\u5927\u5c0f\u7403\u76d8\u53e3",
        "handicap_market": "\u8ba9\u7403\u76d8\u53e3",
        "signal": "\u6700\u7ec8\u4fe1\u53f7",
        "unknown": "\u672a\u77e5\u6a21\u5757",
        "team_strength": "\u7403\u961f\u5b9e\u529b",
        "recent_form": "\u8fd1\u671f\u72b6\u6001",
        "attack": "\u8fdb\u653b\u6307\u6570",
        "defense": "\u9632\u5b88\u6307\u6570",
        "home_advantage": "\u4e3b\u573a\u4f18\u52bf",
        "odds_movement": "\u8d54\u7387\u53d8\u5316",
        "market_heat": "\u5e02\u573a\u70ed\u5ea6",
        "league_strength": "\u8054\u8d5b\u5f3a\u5ea6",
        "fatigue": "\u4f53\u80fd\u75b2\u52b3",
        "injury": "\u4f24\u505c\u98ce\u9669",
        "live_momentum": "\u6eda\u7403\u52a8\u80fd",
    }.get(str(module), str(module))
