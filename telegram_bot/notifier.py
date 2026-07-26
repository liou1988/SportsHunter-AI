from __future__ import annotations

import logging

from telegram import Bot

from config.settings import Settings, get_settings
from pipeline.models import PredictionResult

logger = logging.getLogger(__name__)


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
        text = (
            f"SportsHunter-AI {result.signal.signal.value}\n"
            f"{result.fixture.home_team.name} vs {result.fixture.away_team.name}\n"
            f"Hunter Score: {result.hunter_score.score} {result.hunter_score.grade}\n"
            f"Risk: {result.risk.level.value} ({result.risk.score})\n"
            f"{result.signal.reason}"
        )
        return await self.send_message(text)
