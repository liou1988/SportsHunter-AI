from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from database.repositories import SportsRepository
from database.session import SessionLocal
from datahub.models import OddsMarket, to_plain_dict
from pipeline.archive import ArchiveBatchResult, PredictionArchive
from pipeline.models import PredictionResult
from pipeline.runner import PredictionPipeline

SessionFactory = Callable[[], Session]


def build_today_recommendations(
    pipeline: PredictionPipeline,
    include_pass: bool = False,
    archive: bool = True,
    prediction_archive: PredictionArchive | None = None,
) -> dict:
    results = pipeline.run_today()
    archive_result = (
        (prediction_archive or PredictionArchive()).save_many_if_changed(results)
        if archive
        else ArchiveBatchResult()
    )
    prediction_ids = archive_result.prediction_ids_by_fixture()
    filtered = [
        result
        for result in results
        if include_pass or result.signal.signal.value != "PASS"
    ]
    sorted_results = sorted(filtered, key=lambda result: result.hunter_score.score, reverse=True)
    return {
        "count": len(sorted_results),
        "items": [_recommendation_item(pipeline, result, prediction_ids.get(str(result.fixture.id))) for result in sorted_results],
        "archive": archive_result.to_dict(),
    }


def build_archived_recommendations(
    include_pass: bool = False,
    limit: int = 50,
    session_factory: SessionFactory = SessionLocal,
) -> dict:
    try:
        with session_factory() as session:
            predictions = SportsRepository(session).archived_predictions(limit=limit, include_pass=include_pass)
            items = [_archived_recommendation_item(prediction) for prediction in predictions]
        return {
            "count": len(items),
            "items": items,
            "source": "predictions_archive",
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - archive endpoint should stay diagnostic-friendly
        return {
            "count": 0,
            "items": [],
            "source": "predictions_archive",
            "error": str(exc),
        }


def _recommendation_item(pipeline: PredictionPipeline, result: PredictionResult, prediction_id: int | None = None) -> dict:
    fixture = result.fixture
    odds = _fixture_odds(pipeline, fixture.id)
    market_prediction = _market_prediction(result)
    return {
        "prediction_id": prediction_id,
        "fixture_id": fixture.id,
        "league": fixture.league.name,
        "match": f"{fixture.home_team.name} 对阵 {fixture.away_team.name}",
        "kickoff": fixture.start_time.isoformat(),
        "hunter_score": result.hunter_score.score,
        "confidence": result.hunter_score.confidence,
        "signal": result.signal.signal.value,
        "predicted_side": result.predicted_side,
        "stake": _format_stake(result.signal.stake),
        "reason": result.signal.reason,
        "odds": odds,
        "market_prediction": market_prediction,
        "score_prediction": market_prediction.get("score", {}),
        "total_goals": market_prediction.get("total_goals", {}),
        "handicap": market_prediction.get("handicap", {}),
    }


def _archived_recommendation_item(prediction: Any) -> dict[str, Any]:
    fixture = prediction.fixture
    market_prediction = (prediction.breakdown_json or {}).get("market_prediction", {})
    return {
        "prediction_id": prediction.id,
        "fixture_id": fixture.provider_fixture_id,
        "league": fixture.league.name if fixture.league else "-",
        "match": f"{fixture.home_team.name} 对阵 {fixture.away_team.name}",
        "kickoff": fixture.start_time.isoformat(),
        "hunter_score": prediction.hunter_score,
        "confidence": prediction.confidence,
        "signal": prediction.signal,
        "predicted_side": prediction.predicted_side,
        "stake": _format_stake(prediction.stake),
        "reason": prediction.reason,
        "odds": _archived_odds(fixture),
        "market_prediction": market_prediction,
        "score_prediction": market_prediction.get("score", {}),
        "total_goals": market_prediction.get("total_goals", {}),
        "handicap": market_prediction.get("handicap", {}),
        "created_at": prediction.created_at.isoformat(),
        "settled": fixture.result is not None,
        "result": _result_payload(fixture.result),
    }


def _archived_odds(fixture: Any) -> dict:
    snapshots = sorted(fixture.odds_snapshots or [], key=lambda item: item.captured_at, reverse=True)
    if not snapshots:
        return {}
    latest = snapshots[0]
    return {
        "provider": latest.provider,
        "bookmaker": latest.bookmaker,
        "market": latest.market,
        "line": latest.line,
        "home": latest.home,
        "draw": latest.draw,
        "away": latest.away,
        "over": latest.over,
        "under": latest.under,
        "captured_at": latest.captured_at.isoformat(),
    }


def _result_payload(result: Any) -> dict | None:
    if result is None:
        return None
    return {
        "home_score": result.home_score,
        "away_score": result.away_score,
        "winner": result.winner,
        "settled_at": result.settled_at.isoformat() if result.settled_at else None,
    }


def _fixture_odds(pipeline: PredictionPipeline, fixture_id: str) -> dict | list:
    try:
        odds_items = pipeline.context.datahub.get_odds(fixture_id)
    except Exception:  # noqa: BLE001 - recommendation output should survive missing odds
        return {}
    european = next((odds for odds in odds_items if odds.market == OddsMarket.EUROPEAN), None)
    if european is not None:
        return to_plain_dict(european)
    return to_plain_dict(odds_items)


def _format_stake(stake: float) -> str:
    if float(stake).is_integer():
        return f"{int(stake)}U"
    return f"{stake:g}U"


def _market_prediction(result: PredictionResult) -> dict:
    prediction = getattr(result, "market_prediction", None)
    if prediction is None:
        return {}
    to_dict = getattr(prediction, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    if isinstance(prediction, dict):
        return prediction
    return {}
