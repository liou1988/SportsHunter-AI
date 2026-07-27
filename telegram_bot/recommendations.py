from __future__ import annotations

from dataclasses import dataclass

from api.services.recommendations import build_today_recommendations
from pipeline.runner import PredictionPipeline
from telegram_bot.localization import (
    format_beijing_time,
    translate_league_name,
    translate_match_text,
    translate_signal,
    translate_team_name,
)
from telegram_bot.notifier import TelegramNotifier, TelegramSendResult


@dataclass(slots=True)
class TelegramPushResult:
    sent: bool
    count: int
    message: str
    success: bool | None = None
    error: str | None = None
    error_code: str | None = None
    message_id: int | None = None

    def to_dict(self) -> dict:
        return {
            "success": self.sent if self.success is None else self.success,
            "sent": self.sent,
            "count": self.count,
            "message": self.message,
            "error": self.error,
            "error_code": self.error_code,
            "message_id": self.message_id,
        }


class RecommendationTelegramPusher:
    def __init__(
        self,
        pipeline: PredictionPipeline | None = None,
        notifier: TelegramNotifier | None = None,
    ) -> None:
        self.pipeline = pipeline or PredictionPipeline()
        self.notifier = notifier or TelegramNotifier()

    async def push_today(self) -> TelegramPushResult:
        recommendations = build_today_recommendations(self.pipeline, include_pass=False)
        message = format_recommendations_message(recommendations)
        send_result = await _send_with_result(self.notifier, message)
        return TelegramPushResult(
            success=send_result.success,
            sent=send_result.sent,
            count=recommendations["count"],
            message=message,
            error=send_result.error,
            error_code=send_result.error_code,
            message_id=send_result.message_id,
        )

    async def send_test_message(self) -> TelegramPushResult:
        message = "SportsHunter AI 测试消息"
        send_result = await _send_with_result(self.notifier, message)
        return TelegramPushResult(
            success=send_result.success,
            sent=send_result.sent,
            count=0,
            message=message,
            error=send_result.error,
            error_code=send_result.error_code,
            message_id=send_result.message_id,
        )


async def _send_with_result(notifier: TelegramNotifier, message: str) -> TelegramSendResult:
    sender = getattr(notifier, "send_message_with_result", None)
    if callable(sender):
        return await sender(message)
    sent = await notifier.send_message(message)
    return TelegramSendResult(success=sent, sent=sent)


def format_recommendations_message(recommendations: dict) -> str:
    lines = ["SportsHunter AI 今日推荐", f"共 {recommendations['count']} 场", ""]
    if recommendations["count"] == 0:
        lines.append("今日没有符合条件的推荐。")
        return "\n".join(lines)

    for index, item in enumerate(recommendations["items"], start=1):
        signal = translate_signal(str(item["signal"]))
        league = translate_league_name(str(item["league"]))
        match = translate_match_text(str(item["match"]))
        predicted_side = translate_team_name(item.get("predicted_side")) if item.get("predicted_side") else "-"
        lines.extend(
            [
                f"{index}. {match}",
                f"联赛：{league}",
                f"开赛时间：{format_beijing_time(str(item['kickoff']))}",
                f"信号：{signal}",
                f"推荐方向：{predicted_side}",
                f"仓位：{item['stake']}",
                f"评分：Hunter {item['hunter_score']} | 信心 {item['confidence']}",
                "",
                *format_market_prediction_lines(item.get("market_prediction") or item),
                "",
                "推荐理由：",
                *format_reason_lines(str(item.get("reason") or "")),
                "",
            ]
        )
    return "\n".join(lines).strip()


def format_market_prediction_lines(prediction: dict | None) -> list[str]:
    if not isinstance(prediction, dict) or not prediction:
        return []

    score = prediction.get("score") or prediction.get("score_prediction") or {}
    total_goals = prediction.get("total_goals") or {}
    handicap = prediction.get("handicap") or {}
    lines: list[str] = ["模型预测："]

    if isinstance(score, dict) and score:
        score_text = score.get("text")
        expected_home = score.get("expected_home_goals")
        expected_away = score.get("expected_away_goals")
        if score_text:
            if expected_home is not None and expected_away is not None:
                lines.append(f"  比分预测：{score_text}")
                lines.append(f"  预期进球：{_format_market_number(expected_home)}-{_format_market_number(expected_away)}")
            else:
                lines.append(f"  比分预测：{score_text}")

    if isinstance(total_goals, dict) and total_goals:
        label = total_goals.get("label")
        expected_total = total_goals.get("expected_total")
        confidence = total_goals.get("confidence")
        if label:
            lines.append(f"  大小球：{label}")
            details = []
            if expected_total is not None:
                details.append(f"预期 {_format_market_number(expected_total)} 球")
            if total_goals.get("edge") is not None:
                details.append(f"差值 {_format_market_number(total_goals['edge'])}")
            if confidence is not None:
                details.append(f"信心 {_format_market_number(confidence)}")
            if details:
                lines.append(f"    {' | '.join(details)}")
            if total_goals.get("over_odds") is not None and total_goals.get("under_odds") is not None:
                water = (
                    f"水位 大 {_format_market_number(total_goals['over_odds'])}"
                    f" / 小 {_format_market_number(total_goals['under_odds'])}"
                )
                if total_goals.get("bookmaker"):
                    water = f"{water} | {total_goals['bookmaker']}"
                lines.append(f"    {water}")
            elif total_goals.get("bookmaker"):
                lines.append(f"    来源：{total_goals['bookmaker']}")

    if isinstance(handicap, dict) and handicap:
        lines.extend(_format_handicap_prediction_lines(handicap))

    return lines if len(lines) > 1 else []


def _format_handicap_prediction_lines(handicap: dict) -> list[str]:
    if handicap.get("pick") == "NO_PLAY":
        return [f"  让球：{handicap.get('label') or '观望'}"]
    team = translate_team_name(handicap.get("team")) if handicap.get("team") else None
    line = handicap.get("line")
    line_label = "平手" if line == 0 else _format_market_number(line)
    confidence = handicap.get("confidence")
    lines = [f"  让球：{f'{team} {line_label}'.strip() if team else str(handicap.get('label') or '-')}"]
    details = []
    if handicap.get("edge") is not None:
        details.append(f"盘口差值 {_format_market_number(handicap['edge'])}")
    if confidence is not None:
        details.append(f"信心 {_format_market_number(confidence)}")
    if details:
        lines.append(f"    {' | '.join(details)}")
    if handicap.get("home_odds") is not None and handicap.get("away_odds") is not None:
        water = (
            f"水位 主 {_format_market_number(handicap['home_odds'])} / 客 {_format_market_number(handicap['away_odds'])}"
        )
        if handicap.get("bookmaker"):
            water = f"{water} | {handicap['bookmaker']}"
        lines.append(f"    {water}")
    elif handicap.get("bookmaker"):
        lines.append(f"    来源：{handicap['bookmaker']}")
    return lines


def format_reason_lines(reason: str, max_items: int = 4) -> list[str]:
    parts = _split_reason(reason)
    if not parts:
        return ["  - 暂无补充说明"]
    visible = parts[:max_items]
    lines = [f"  - {part}" for part in visible]
    if len(parts) > max_items:
        lines.append(f"  - 另有 {len(parts) - max_items} 条模型说明已省略")
    return lines


def _split_reason(reason: str) -> list[str]:
    normalized = reason.replace("；", ";").replace("。", ";").replace("\n", ";")
    return [part.strip(" ;；。") for part in normalized.split(";") if part.strip(" ;；。")]


def _format_market_number(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:g}"
