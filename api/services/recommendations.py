from __future__ import annotations

from collections.abc import Callable
import csv
import json
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from database import models as orm
from database.repositories import SportsRepository
from database.session import SessionLocal
from datahub.models import OddsMarket, to_plain_dict
from pipeline.archive import ArchiveBatchResult, PredictionArchive
from pipeline.filters import is_prediction_candidate_fixture
from pipeline.models import PredictionResult

from telegram_bot.localization import translate_fixture_status, translate_league_name, translate_match_text, translate_signal, translate_team_name
from pipeline.runner import PredictionPipeline

SessionFactory = Callable[[], Session]


def build_today_recommendations(
    pipeline: PredictionPipeline,
    include_pass: bool = False,
    archive: bool = True,
    prediction_archive: PredictionArchive | None = None,
) -> dict:
    results = pipeline.run_today()
    current_results = [result for result in results if _is_current_fixture(result.fixture)]
    archive_result = (
        (prediction_archive or PredictionArchive()).save_many_if_changed(current_results)
        if archive
        else ArchiveBatchResult()
    )
    prediction_ids = archive_result.prediction_ids_by_fixture()
    filtered = [
        result
        for result in current_results
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
    alert_archive_path: Path | None = None,
) -> dict:
    try:
        with session_factory() as session:
            predictions = SportsRepository(session).archived_predictions(limit=limit, include_pass=include_pass)
            prediction_items = [_archived_recommendation_item(prediction) for prediction in predictions]
        alert_payload = build_alerted_recommendations(
            alert_archive_path,
            include_pass=include_pass,
            limit=limit,
            session_factory=session_factory,
        )
        alert_items = list(alert_payload.get("items") or [])
        items = _unique_recommendation_items([*alert_items, *prediction_items])[:limit]
        source = (
            "telegram_alert_archive+predictions_archive"
            if alert_archive_path is not None
            else "predictions_archive"
        )
        return {
            "count": len(items),
            "items": items,
            "source": source,
            "error": alert_payload.get("error"),
        }
    except Exception as exc:  # noqa: BLE001 - archive endpoint should stay diagnostic-friendly
        return {
            "count": 0,
            "items": [],
            "source": "predictions_archive",
            "error": str(exc),
        }


def build_alerted_recommendations(
    alert_archive_path: Path | None,
    include_pass: bool = False,
    limit: int = 50,
    session_factory: SessionFactory = SessionLocal,
    now: datetime | None = None,
) -> dict:
    if alert_archive_path is None:
        return {"count": 0, "items": [], "source": "telegram_alert_archive", "error": None}
    alerts_payload = _read_today_alerts(alert_archive_path, now=now)
    if alerts_payload.get("error"):
        return alerts_payload

    alerts = list(alerts_payload.get("alerts") or [])[: max(limit * 5, limit)]
    if not alerts:
        return {"count": 0, "items": [], "source": "telegram_alert_archive", "error": None}

    fixture_ids = [str(alert.get("fixture_id") or "") for alert in alerts if alert.get("fixture_id")]
    predictions_by_fixture_id = _latest_predictions_by_provider_fixture_id(fixture_ids, session_factory)
    items: list[dict[str, Any]] = []
    for alert in alerts:
        signal = str(alert.get("signal") or "")
        if not include_pass and signal == "PASS":
            continue
        fixture_id = str(alert.get("fixture_id") or "")
        prediction = predictions_by_fixture_id.get(fixture_id)
        item = _archived_recommendation_item(prediction) if prediction is not None else _alert_only_recommendation_item(alert)
        item.update(
            {
                "alert_key": alert.get("key"),
                "alert_sent_at": alert.get("sent_at"),
                "alert_message_id": alert.get("message_id"),
                "source": "telegram_alert_archive",
            }
        )
        if signal:
            item["signal"] = signal
        if alert.get("hunter_score") is not None:
            item["hunter_score"] = alert.get("hunter_score")
        if alert.get("confidence") is not None:
            item["confidence"] = alert.get("confidence")
        items.append(item)
        if len(items) >= limit:
            break
    return {
        "count": len(items),
        "items": _unique_recommendation_items(items)[:limit],
        "source": "telegram_alert_archive",
        "error": None,
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


def _is_current_fixture(fixture: Any, now: datetime | None = None) -> bool:
    return is_prediction_candidate_fixture(fixture, now)


def _iso_utc(value: datetime | None) -> str | None:
    utc_value = _as_utc(value)
    return utc_value.isoformat() if utc_value else None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _recommendation_item(pipeline: PredictionPipeline, result: PredictionResult, prediction_id: int | None = None) -> dict:
    fixture = result.fixture
    odds = _fixture_odds(pipeline, fixture.id)
    market_prediction = _localize_market_prediction(_market_prediction(result))
    return {
        "prediction_id": prediction_id,
        "fixture_id": fixture.id,
        "league": translate_league_name(fixture.league.name),
        "match": translate_match_text(f"{fixture.home_team.name} vs {fixture.away_team.name}"),
        "kickoff": _iso_utc(fixture.start_time),
        "hunter_score": result.hunter_score.score,
        "confidence": result.hunter_score.confidence,
        "signal": result.signal.signal.value,
        "fixture_status": fixture.status.value,
        "status_label": translate_fixture_status(fixture.status.value),
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
        "id": prediction.id,
        "fixture_id": fixture.provider_fixture_id,
        "league": translate_league_name(fixture.league.name) if fixture.league else "-",
        "match": translate_match_text(f"{fixture.home_team.name} vs {fixture.away_team.name}"),
        "kickoff": _iso_utc(fixture.start_time),
        "hunter_score": prediction.hunter_score,
        "confidence": prediction.confidence,
        "signal": prediction.signal,
        "fixture_status": fixture.status,
        "status_label": translate_fixture_status(fixture.status),
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


def _read_today_alerts(alert_archive_path: Path, now: datetime | None = None) -> dict[str, Any]:
    path = Path(alert_archive_path)
    if not path.exists():
        return {"count": 0, "alerts": [], "source": "telegram_alert_archive", "error": None}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"count": 0, "alerts": [], "source": "telegram_alert_archive", "error": str(exc)}
    if not isinstance(payload, dict):
        return {"count": 0, "alerts": [], "source": "telegram_alert_archive", "error": "alert archive is not an object"}

    today_key = _beijing_date_key(now or datetime.now(timezone.utc))
    alerts: list[dict[str, Any]] = []
    for key, value in payload.items():
        if not isinstance(value, dict):
            continue
        sent_at = _parse_datetime(value.get("sent_at"))
        if sent_at is None or _beijing_date_key(sent_at) != today_key:
            continue
        alerts.append({"key": key, **value})
    alerts.sort(key=lambda item: str(item.get("sent_at") or ""), reverse=True)
    return {"count": len(alerts), "alerts": alerts, "source": "telegram_alert_archive", "error": None}


def _latest_predictions_by_provider_fixture_id(
    provider_fixture_ids: list[str],
    session_factory: SessionFactory,
) -> dict[str, Any]:
    ids = [fixture_id for fixture_id in dict.fromkeys(provider_fixture_ids) if fixture_id]
    if not ids:
        return {}
    with session_factory() as session:
        predictions = list(
            session.scalars(
                select(orm.Prediction)
                .join(orm.Fixture, orm.Prediction.fixture_id == orm.Fixture.id)
                .where(orm.Fixture.provider_fixture_id.in_(ids))
                .options(
                    selectinload(orm.Prediction.fixture).selectinload(orm.Fixture.league),
                    selectinload(orm.Prediction.fixture).selectinload(orm.Fixture.home_team),
                    selectinload(orm.Prediction.fixture).selectinload(orm.Fixture.away_team),
                    selectinload(orm.Prediction.fixture).selectinload(orm.Fixture.odds_snapshots),
                    selectinload(orm.Prediction.fixture).selectinload(orm.Fixture.result),
                )
                .order_by(desc(orm.Prediction.created_at), desc(orm.Prediction.id))
            )
        )
        latest: dict[str, Any] = {}
        for prediction in predictions:
            fixture_id = str(prediction.fixture.provider_fixture_id)
            latest.setdefault(fixture_id, prediction)
        return latest


def _alert_only_recommendation_item(alert: dict[str, Any]) -> dict[str, Any]:
    fixture_id = str(alert.get("fixture_id") or "")
    return {
        "prediction_id": None,
        "id": None,
        "fixture_id": fixture_id,
        "league": "-",
        "match": f"Fixture {fixture_id}" if fixture_id else "-",
        "kickoff": None,
        "hunter_score": alert.get("hunter_score"),
        "confidence": alert.get("confidence"),
        "signal": alert.get("signal"),
        "fixture_status": "unknown",
        "status_label": translate_fixture_status("unknown"),
        "predicted_side": None,
        "stake": "-",
        "reason": "-",
        "odds": {},
        "market_prediction": {},
        "score_prediction": {},
        "total_goals": {},
        "handicap": {},
        "created_at": None,
        "settled": False,
        "result": None,
    }


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _beijing_date_key(value: datetime) -> str:
    return _as_utc(value).astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()


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
