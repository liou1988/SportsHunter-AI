from __future__ import annotations

import logging

from fastapi import APIRouter

from telegram_bot.notifier import TelegramNotifier

router = APIRouter(prefix="/api/telegram", tags=["telegram"])
TEST_TELEGRAM_MESSAGE = "SportsHunter AI 测试消息"
logger = logging.getLogger(__name__)


@router.post("/test")
async def telegram_test() -> dict:
    try:
        sent = await TelegramNotifier().send_message(TEST_TELEGRAM_MESSAGE)
    except Exception as exc:  # noqa: BLE001 - never expose Telegram SDK errors as 500
        logger.exception("telegram test endpoint failed", exc_info=exc)
        sent = False
    return {"success": bool(sent), "sent": bool(sent)}
