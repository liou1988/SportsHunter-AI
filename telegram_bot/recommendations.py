from __future__ import annotations

from dataclasses import dataclass

from api.services.recommendations import build_today_recommendations
from pipeline.runner import PredictionPipeline
from telegram_bot.notifier import TelegramNotifier


@dataclass(slots=True)
class TelegramPushResult:
    sent: bool
    count: int
    message: str

    def to_dict(self) -> dict:
        return {"sent": self.sent, "count": self.count, "message": self.message}


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
        sent = await self.notifier.send_message(message)
        return TelegramPushResult(sent=sent, count=recommendations["count"], message=message)

    async def send_test_message(self) -> TelegramPushResult:
        message = "SportsHunter AI 测试消息"
        sent = await self.notifier.send_message(message)
        return TelegramPushResult(sent=sent, count=0, message=message)


def format_recommendations_message(recommendations: dict) -> str:
    lines = ["SportsHunter AI 今日推荐", ""]
    if recommendations["count"] == 0:
        lines.append("今日没有符合条件的推荐。")
        return "\n".join(lines)

    for index, item in enumerate(recommendations["items"], start=1):
        lines.extend(
            [
                f"{index}. {item['match']}",
                f"联赛: {item['league']}",
                f"开赛: {item['kickoff']}",
                f"信号: {item['signal']} | Hunter Score: {item['hunter_score']} | Confidence: {item['confidence']}",
                f"方向: {item['predicted_side'] or '-'} | 仓位: {item['stake']}",
                f"理由: {item['reason']}",
                "",
            ]
        )
    return "\n".join(lines).strip()
