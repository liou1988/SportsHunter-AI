from __future__ import annotations

from collections.abc import Callable
import csv
from io import StringIO
from typing import Any

from sqlalchemy.orm import Session

from database.repositories import SportsRepository
from database.session import SessionLocal
from datahub.models import OddsMarket, to_plain_dict
from pipeline.archive import ArchiveBatchResult, PredictionArchive
from pipeline.models import PredictionResult

from telegram_bot.localization import translate_league_name, translate_match_text, translate_signal, translate_team_name
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
            items = _unique_recommendation_items([_archived_recommendation_item(prediction) for prediction in predictions])
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


def build_recommendations_export_csv(
    include_pass: bool = False,
    limit: int = 200,
    session_factory: SessionFactory = SessionLocal,
) -> str:
    payload = build_archived_recommendations(include_pass=include_pass, limit=limit, session_factory=session_factory)
    output = StringIO()
    output.write("\ufeff")
    writer = csv.DictWriter(output, fieldnames=_EXPORT_COLUMNS)
    writer.writeheader()
    for item in payload.get("items", []):
        writer.writerow(_export_row(item))
    return output.getvalue()


_EXPORT_COLUMNS = [
    "\u8054\u8d5b",
    "\u6bd4\u8d5b",
    "\u5f00\u8d5b\u65f6\u95f4",
    "\u4fe1\u53f7",
    "Hunter\u8bc4\u5206",
    "\u4fe1\u5fc3",
    "\u9884\u6d4b\u65b9\u5411",
    "\u4ed3\u4f4d",
    "\u6bd4\u5206\u9884\u6d4b",
    "\u5927\u5c0f\u7403",
    "\u8ba9\u7403",
    "\u8d54\u7387\u516c\u53f8",
    "\u6b27\u8d54\u4e3b\u80dc",
    "\u6b27\u8d54\u5e73\u5c40",
    "\u6b27\u8d54\u5ba2\u80dc",
    "\u63a8\u8350\u7406\u7531",
]


def _export_row(item: dict[str, Any]) -> dict[str, Any]:
    odds = item.get("odds") if isinstance(item.get("odds"), dict) else {}
    score = item.get("score_prediction") if isinstance(item.get("score_prediction"), dict) else {}
    total = item.get("total_goals") if isinstance(item.get("total_goals"), dict) else {}
    handicap = item.get("handicap") if isinstance(item.get("handicap"), dict) else {}
    return {
        "\u8054\u8d5b": item.get("league", "-"),
        "\u6bd4\u8d5b": item.get("match", "-"),
        "\u5f00\u8d5b\u65f6\u95f4": item.get("kickoff", "-"),
        "\u4fe1\u53f7": translate_signal(str(item.get("signal", ""))) if item.get("signal") else "-",
        "Hunter\u8bc4\u5206": item.get("hunter_score", "-"),
        "\u4fe1\u5fc3": item.get("confidence", "-"),
        "\u9884\u6d4b\u65b9\u5411": item.get("predicted_side") or "-",
        "\u4ed3\u4f4d": item.get("stake") or "-",
        "\u6bd4\u5206\u9884\u6d4b": score.get("text") or "-",
        "\u5927\u5c0f\u7403": total.get("label") or "-",
        "\u8ba9\u7403": handicap.get("label") or "-",
        "\u8d54\u7387\u516c\u53f8": odds.get("bookmaker") or odds.get("provider") or "-",
        "\u6b27\u8d54\u4e3b\u80dc": odds.get("home") or "-",
        "\u6b27\u8d54\u5e73\u5c40": odds.get("draw") or "-",
        "\u6b27\u8d54\u5ba2\u80dc": odds.get("away") or "-",
        "\u63a8\u8350\u7406\u7531": item.get("reason") or "-",
    }


def _recommendation_item(pipeline: PredictionPipeline, result: PredictionResult, prediction_id: int | None = None) -> dict:
    fixture = result.fixture
    odds = _fixture_odds(pipeline, fixture.id)
    market_prediction = _localize_market_prediction(_market_prediction(result))
    return {
        "prediction_id": prediction_id,
        "fixture_id": fixture.id,
        "league": translate_league_name(fixture.league.name),
        "match": translate_match_text(f"{fixture.home_team.name} vs {fixture.away_team.name}"),
        "kickoff": fixture.start_time.isoformat(),
        "hunter_score": result.hunter_score.score,
        "confidence": result.hunter_score.confidence,
        "signal": result.signal.signal.value,
        "predicted_side": translate_team_name(result.predicted_side) if result.predicted_side else None,
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
    market_prediction = _localize_market_prediction((prediction.breakdown_json or {}).get("market_prediction", {}))
    return {
        "prediction_id": prediction.id,
        "fixture_id": fixture.provider_fixture_id,
        "league": translate_league_name(fixture.league.name) if fixture.league else "-",
        "match": translate_match_text(f"{fixture.home_team.name} vs {fixture.away_team.name}"),
        "kickoff": fixture.start_time.isoformat(),
        "hunter_score": prediction.hunter_score,
        "confidence": prediction.confidence,
        "signal": prediction.signal,
        "predicted_side": translate_team_name(prediction.predicted_side) if prediction.predicted_side else None,
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


def _unique_recommendation_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = (
            str(item.get("league") or "").casefold().strip(),
            str(item.get("match") or "").casefold().strip(),
            str(item.get("kickoff") or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


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


def _localize_market_prediction(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}
    localized = dict(payload)
    if localized.get("predicted_side"):
        localized["predicted_side"] = translate_team_name(localized["predicted_side"])
    handicap = localized.get("handicap")
    if isinstance(handicap, dict):
        localized["handicap"] = dict(handicap)
        if localized["handicap"].get("team"):
            localized["handicap"]["team"] = translate_team_name(localized["handicap"]["team"])
    return localized
