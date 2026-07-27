from __future__ import annotations

from datahub.models import OddsMarket, to_plain_dict
from pipeline.models import PredictionResult
from pipeline.runner import PredictionPipeline


def build_today_recommendations(pipeline: PredictionPipeline, include_pass: bool = False) -> dict:
    results = pipeline.run_today()
    filtered = [
        result
        for result in results
        if include_pass or result.signal.signal.value != "PASS"
    ]
    sorted_results = sorted(filtered, key=lambda result: result.hunter_score.score, reverse=True)
    return {
        "count": len(sorted_results),
        "items": [_recommendation_item(pipeline, result) for result in sorted_results],
    }


def _recommendation_item(pipeline: PredictionPipeline, result: PredictionResult) -> dict:
    fixture = result.fixture
    odds = _fixture_odds(pipeline, fixture.id)
    market_prediction = _market_prediction(result)
    return {
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
