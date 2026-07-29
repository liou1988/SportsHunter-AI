from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from database import models as orm
from database.repositories import SportsRepository
from database.session import SessionLocal

SessionFactory = Callable[[], Session]

PERIOD_DAYS = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
}


class EvaluationDataset:
    def __init__(self, session_factory: SessionFactory = SessionLocal) -> None:
        self.session_factory = session_factory

    def rows(self, period: str = "daily") -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(days=PERIOD_DAYS.get(period, 1))
        with self.session_factory() as session:
            repo = SportsRepository(session)
            settled = repo.settled_predictions(since=since)
            return [_build_row(prediction, fixture, result) for prediction, fixture, result in settled]

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


def _build_row(prediction: orm.Prediction, fixture: orm.Fixture, result: orm.MatchResult) -> dict:
    market_prediction = (prediction.breakdown_json or {}).get("market_prediction", {})
    score_prediction = market_prediction.get("score", {})
    total_goals = market_prediction.get("total_goals", {})
    handicap = market_prediction.get("handicap", {})
    winner_side = _winner_side(result.home_score, result.away_score)
    moneyline_pick = str(market_prediction.get("moneyline_pick") or "").upper()
    won = _moneyline_hit(moneyline_pick, prediction.predicted_side, fixture, winner_side)
    stake = float(prediction.stake or 0.0)
    actionable = stake > 0 and prediction.signal not in {"PASS", "BLOCK"}

    row = {
        "prediction_id": prediction.id,
        "fixture_id": fixture.id,
        "league": fixture.league.name if fixture.league else "unknown",
        "fixture": f"{fixture.home_team.name} vs {fixture.away_team.name}",
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
            "推荐方向命中，当前评分、风险和市场信号保持一致；"
            f"预测比分 {row.get('predicted_score')}，实际比分 {_result_score(row)}，"
            f"比分误差 {row.get('score_error')}，大小球 {row.get('total_goals_hit')}，让球 {row.get('handicap_hit')}。"
        )
    module = row.get("primary_error_module") or "unknown"
    return (
        f"推荐未命中，需要复核 {module}；"
        f"预测比分 {row.get('predicted_score')}，实际比分 {_result_score(row)}，"
        f"比分误差 {row.get('score_error')}，大小球 {row.get('total_goals_hit')}，让球 {row.get('handicap_hit')}。"
    )


def _result_score(row: dict) -> str:
    home_score = row.get("home_score")
    away_score = row.get("away_score")
    if home_score is None or away_score is None:
        return "-"
    return f"{home_score}-{away_score}"
