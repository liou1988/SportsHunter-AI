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
    lines = ["SportsHunter AI 今日推荐", ""]
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
                f"信号：{signal} | 猎手评分：{item['hunter_score']} | 信心：{item['confidence']}",
                f"推荐方向：{predicted_side} | 仓位：{item['stake']}",
                f"推荐理由：{item['reason']}",
                "",
            ]
        )
    return "\n".join(lines).strip()
