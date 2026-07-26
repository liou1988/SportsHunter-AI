from __future__ import annotations

import logging

from telegram import Bot

from config.settings import Settings, get_settings
from pipeline.models import PredictionResult

logger = logging.getLogger(__name__)


SIGNAL_LABELS = {
    "STRONG_BUY": "强烈推荐",
    "BUY": "推荐",
    "WATCH": "观察",
    "PASS": "跳过",
    "BLOCK": "风控拦截",
}

RISK_LABELS = {
    "LOW": "低",
    "MEDIUM": "中",
    "HIGH": "高",
    "BLOCK": "拦截",
}


class TelegramNotifier:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def send_message(self, text: str) -> bool:
        if not self.settings.telegram_is_enabled:
            logger.info("telegram is disabled")
            return False
        bot_token = self.settings.telegram_effective_bot_token
        chat_id = self.settings.telegram_effective_chat_id
        if not bot_token or not chat_id:
            logger.warning("telegram enabled but token/chat id is missing")
            return False
        try:
            bot = Bot(bot_token)
            await bot.send_message(chat_id=chat_id, text=text)
            return True
        except Exception as exc:  # noqa: BLE001 - Telegram test endpoint must not crash the API
            logger.exception("telegram send failed", exc_info=exc)
            return False

    async def send_prediction(self, result: PredictionResult) -> bool:
        signal = SIGNAL_LABELS.get(result.signal.signal.value, result.signal.signal.value)
        risk = RISK_LABELS.get(result.risk.level.value, result.risk.level.value)
        text = (
            f"SportsHunter AI 预测信号：{signal}\n"
            f"{result.fixture.home_team.name} 对阵 {result.fixture.away_team.name}\n"
            f"猎手评分：{result.hunter_score.score} {result.hunter_score.grade}\n"
            f"风险等级：{risk}（{result.risk.score}）\n"
            f"{result.signal.reason}"
        )
        return await self.send_message(text)
