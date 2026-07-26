from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from api.services.recommendations import build_today_recommendations
from pipeline.runner import PredictionPipeline
from telegram_bot.notifier import TelegramNotifier, TelegramSendResult


SIGNAL_LABELS = {
    "STRONG_BUY": "强烈推荐",
    "BUY": "推荐",
    "WATCH": "观察",
    "PASS": "跳过",
    "BLOCK": "风控拦截",
}

LEAGUE_LABELS_BY_NAME = {
    "English Premier League": "英格兰超级联赛",
    "Spanish LaLiga": "西班牙甲级联赛",
    "Italian Serie A": "意大利甲级联赛",
    "German Bundesliga": "德国甲级联赛",
    "French Ligue 1": "法国甲级联赛",
    "Portuguese Primeira Liga": "葡萄牙超级联赛",
    "Dutch Eredivisie": "荷兰甲级联赛",
    "UEFA Champions League": "欧洲冠军联赛",
    "UEFA Europa League": "欧足联欧洲联赛",
    "UEFA Europa Conference League": "欧足联欧洲协会联赛",
    "FIFA World Cup": "世界杯",
    "International Friendly": "国际友谊赛",
    "Major League Soccer": "美国职业足球大联盟",
    "Liga MX": "墨西哥甲级联赛",
    "Brazilian Serie A": "巴西甲级联赛",
    "Brazilian Serie B": "巴西乙级联赛",
    "Argentine Liga Profesional de Futbol": "阿根廷甲级联赛",
    "Argentine Primera Nacional": "阿根廷乙级联赛",
}


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
        signal = SIGNAL_LABELS.get(str(item["signal"]), str(item["signal"]))
        league = LEAGUE_LABELS_BY_NAME.get(str(item["league"]), str(item["league"]))
        match = str(item["match"]).replace(" vs ", " 对阵 ")
        lines.extend(
            [
                f"{index}. {match}",
                f"联赛：{league}",
                f"开赛时间：{_format_beijing_time(str(item['kickoff']))}",
                f"信号：{signal} | 猎手评分：{item['hunter_score']} | 信心：{item['confidence']}",
                f"推荐方向：{item['predicted_side'] or '-'} | 仓位：{item['stake']}",
                f"推荐理由：{item['reason']}",
                "",
            ]
        )
    return "\n".join(lines).strip()


def _format_beijing_time(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return f"{parsed.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M')} 北京时间"
