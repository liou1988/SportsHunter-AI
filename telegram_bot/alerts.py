from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from config.settings import Settings, get_settings
from datahub.models import OddsMarket, to_plain_dict
from pipeline.archive import PredictionArchive
from pipeline.models import PredictionResult
from pipeline.recommendation_gate import RecommendationGate
from pipeline.runner import PredictionPipeline
from telegram_bot.localization import (
    format_beijing_time,
    translate_league_name,
    translate_match_text,
    translate_signal,
    translate_team_name,
)
from telegram_bot.notifier import TelegramNotifier, TelegramSendResult
from telegram_bot.recommendations import _send_with_result, format_market_prediction_lines, format_reason_lines

logger = logging.getLogger(__name__)

BEIJING_TZ = ZoneInfo("Asia/Shanghai")
ALERT_FIXTURE_STATUSES = {"scheduled", "unknown"}


@dataclass(slots=True)
class AlertItem:
    key: str
    fixture_id: str
    signal: str
    hunter_score: float
    confidence: float
    message_id: int | None = None

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "fixture_id": self.fixture_id,
            "signal": self.signal,
            "hunter_score": self.hunter_score,
            "confidence": self.confidence,
            "message_id": self.message_id,
        }


@dataclass(slots=True)
class AlertPushResult:
    success: bool
    sent: bool
    evaluated_count: int
    eligible_count: int
    pushed_count: int
    skipped_count: int
    message: str
    alerts: list[AlertItem] = field(default_factory=list)
    error: str | None = None
    error_code: str | None = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "sent": self.sent,
            "evaluated_count": self.evaluated_count,
            "eligible_count": self.eligible_count,
            "pushed_count": self.pushed_count,
            "skipped_count": self.skipped_count,
            "message": self.message,
            "alerts": [item.to_dict() for item in self.alerts],
            "error": self.error,
            "error_code": self.error_code,
        }


class AlertArchive:
    def __init__(self, path: Path, retention_days: int = 7) -> None:
        self.path = path
        self.retention_days = max(1, retention_days)

    def has(self, key: str) -> bool:
        return key in self._read()

    def mark(self, key: str, payload: dict[str, Any]) -> None:
        items = self._read()
        items[key] = {
            **payload,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write(self._prune(items))

    def _read(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("telegram alert archive is unreadable; starting fresh", extra={"path": str(self.path)}, exc_info=exc)
            return {}
        return raw if isinstance(raw, dict) else {}

    def _write(self, items: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(items, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def _prune(self, items: dict[str, dict]) -> dict[str, dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        pruned: dict[str, dict] = {}
        for key, item in items.items():
            sent_at = _parse_datetime(item.get("sent_at"))
            if sent_at is None or sent_at >= cutoff:
                pruned[key] = item
        return pruned


class RecommendationAlertPusher:
    def __init__(
        self,
        pipeline: PredictionPipeline | None = None,
        notifier: TelegramNotifier | None = None,
        archive: AlertArchive | None = None,
        prediction_archive: PredictionArchive | None = None,
        settings: Settings | None = None,
        gate: RecommendationGate | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.pipeline = pipeline or PredictionPipeline()
        self.notifier = notifier or TelegramNotifier(self.settings)
        self.archive = archive or AlertArchive(
            self.settings.telegram_alert_archive_path,
            self.settings.telegram_alert_retention_days,
        )
        self.prediction_archive = prediction_archive or PredictionArchive()
        self.gate = gate or RecommendationGate(self.settings)

    async def push_new(self) -> AlertPushResult:
        results = self.pipeline.run_today()
        candidates = self._eligible_results(results)
        fresh = [result for result in candidates if not self.archive.has(self._alert_key(result))]
        skipped_count = len(candidates) - len(fresh)

        if not fresh:
            return AlertPushResult(
                success=True,
                sent=False,
                evaluated_count=len(results),
                eligible_count=len(candidates),
                pushed_count=0,
                skipped_count=skipped_count,
                message="没有新的合适比赛，未发送 Telegram。",
            )

        pushed: list[AlertItem] = []
        for result in fresh:
            message = format_recommendation_alert_message(self.pipeline, result)
            send_result = await _send_with_result(self.notifier, message)
            if not send_result.sent:
                return AlertPushResult(
                    success=send_result.success,
                    sent=False,
                    evaluated_count=len(results),
                    eligible_count=len(candidates),
                    pushed_count=len(pushed),
                    skipped_count=skipped_count,
                    message="发现合适比赛，但 Telegram 发送失败。",
                    alerts=pushed,
                    error=send_result.error,
                    error_code=send_result.error_code,
                )

            try:
                save_if_changed = getattr(self.prediction_archive, "save_if_changed", None)
                if callable(save_if_changed):
                    save_if_changed(result)
                else:
                    self.prediction_archive.save(result)
            except Exception as exc:  # noqa: BLE001 - delivery should not be undone by archive failure
                logger.exception("telegram alert prediction archive failed", extra={"fixture_id": result.fixture.id}, exc_info=exc)

            item = AlertItem(
                key=self._alert_key(result),
                fixture_id=result.fixture.id,
                signal=result.signal.signal.value,
                hunter_score=result.hunter_score.score,
                confidence=result.hunter_score.confidence,
                message_id=send_result.message_id,
            )
            self.archive.mark(
                item.key,
                {
                    "fixture_id": item.fixture_id,
                    "signal": item.signal,
                    "hunter_score": item.hunter_score,
                    "confidence": item.confidence,
                    "message_id": item.message_id,
                },
            )
            pushed.append(item)

        return AlertPushResult(
            success=True,
            sent=True,
            evaluated_count=len(results),
            eligible_count=len(candidates),
            pushed_count=len(pushed),
            skipped_count=skipped_count,
            message=f"已推送 {len(pushed)} 场新推荐。",
            alerts=pushed,
        )

    def _eligible_results(self, results: list[PredictionResult]) -> list[PredictionResult]:
        allowed = {str(signal).strip().upper() for signal in self.settings.telegram_alert_signals}
        now = datetime.now(timezone.utc)
        candidates = [
            result
            for result in results
            if result.signal.signal.value in allowed and result.signal.stake > 0
            and _is_unstarted_alert_fixture(result.fixture, now)
            and self._passes_recommendation_gate(result, now)
        ]
        return sorted(candidates, key=lambda result: result.hunter_score.score, reverse=True)

    def _passes_recommendation_gate(self, result: PredictionResult, now: datetime) -> bool:
        odds = list(getattr(result, "odds", []) or [])
        if not odds:
            odds = _load_fixture_odds(self.pipeline, result.fixture.id)
        decision = self.gate.evaluate(result, odds=odds, now=now)
        if not decision.passed:
            logger.info(
                "telegram alert recommendation gate blocked fixture",
                extra={
                    "fixture_id": result.fixture.id,
                    "reasons": decision.reasons,
                    "metrics": decision.metrics,
                },
            )
        return decision.passed

    @staticmethod
    def _alert_key(result: PredictionResult) -> str:
        fixture = result.fixture
        kickoff = fixture.start_time.astimezone(timezone.utc).strftime("%Y%m%d%H%M")
        return f"{fixture.provider}:{fixture.id}:{kickoff}:{result.signal.signal.value}"


def format_recommendation_alert_message(pipeline: PredictionPipeline, result: PredictionResult) -> str:
    fixture = result.fixture
    odds = _fixture_odds(pipeline, fixture.id)
    league = translate_league_name(fixture.league.name)
    match = translate_match_text(f"{fixture.home_team.name} vs {fixture.away_team.name}")
    predicted_side = translate_team_name(result.predicted_side) if result.predicted_side else "-"
    signal = translate_signal(result.signal.signal.value)
    lines = [
        "SportsHunter AI 发现合适比赛",
        "",
        match,
        f"联赛：{league}",
        f"开赛时间：{format_beijing_time(fixture.start_time)}",
        f"信号：{signal}",
        f"推荐方向：{predicted_side}",
        f"仓位：{_format_stake(result.signal.stake)}",
        f"评分：Hunter {result.hunter_score.score} {result.hunter_score.grade}",
        f"信心：{result.hunter_score.confidence}",
        "",
        *format_market_prediction_lines(result.market_prediction.to_dict()),
        "",
        "推荐理由：",
        *format_reason_lines(result.signal.reason),
    ]
    odds_lines = _format_odds_lines(odds)
    if odds_lines:
        lines.extend(["", *odds_lines])
    return "\n".join(lines)


def _format_odds_lines(odds: dict | list) -> list[str]:
    if not isinstance(odds, dict) or not odds:
        return []
    home = odds.get("home")
    draw = odds.get("draw")
    away = odds.get("away")
    if home is None and draw is None and away is None:
        return []
    bookmaker = odds.get("bookmaker") or odds.get("provider") or "-"
    return [
        f"赔率：{bookmaker}",
        f"  主胜：{home or '-'}",
        f"  平局：{draw or '-'}",
        f"  客胜：{away or '-'}",
    ]


def _fixture_odds(pipeline: PredictionPipeline, fixture_id: str) -> dict | list:
    odds_items = _load_fixture_odds(pipeline, fixture_id)
    european = next((odds for odds in odds_items if odds.market == OddsMarket.EUROPEAN), None)
    if european is not None:
        return to_plain_dict(european)
    return to_plain_dict(odds_items)


def _load_fixture_odds(pipeline: PredictionPipeline, fixture_id: str) -> list:
    try:
        return list(pipeline.context.datahub.get_odds(fixture_id))
    except Exception:  # noqa: BLE001 - alert output should survive missing odds
        return []


def _is_unstarted_alert_fixture(fixture: Any, now: datetime | None = None) -> bool:
    start_time = _as_utc(getattr(fixture, "start_time", None))
    if start_time is None:
        return False
    now = _as_utc(now) or datetime.now(timezone.utc)
    if start_time.astimezone(BEIJING_TZ).date() != now.astimezone(BEIJING_TZ).date():
        return False
    if start_time < now:
        return False
    raw_status = getattr(fixture, "status", "unknown")
    status = str(getattr(raw_status, "value", raw_status)).lower()
    return status in ALERT_FIXTURE_STATUSES


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_stake(stake: float) -> str:
    if float(stake).is_integer():
        return f"{int(stake)}U"
    return f"{stake:g}U"


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
