from __future__ import annotations

import logging

from telegram import Bot

from config.settings import Settings, get_settings
from pipeline.models import PredictionResult

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def send_prediction(self, result: PredictionResult) -> bool:
        if not self.settings.telegram_push_enabled:
            return False
        if not self.settings.telegram_bot_token or not self.settings.telegram_chat_id:
            logger.warning("telegram push enabled but token/chat id is missing")
            return False
        text = (
            f"SportsHunter-AI {result.signal.signal.value}\n"
            f"{result.fixture.home_team.name} vs {result.fixture.away_team.name}\n"
            f"Hunter Score: {result.hunter_score.score} {result.hunter_score.grade}\n"
            f"Risk: {result.risk.level.value} ({result.risk.score})\n"
            f"{result.signal.reason}"
        )
        bot = Bot(self.settings.telegram_bot_token)
        await bot.send_message(chat_id=self.settings.telegram_chat_id, text=text)
        return True
