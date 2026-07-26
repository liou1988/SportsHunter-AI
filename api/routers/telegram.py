from __future__ import annotations

from fastapi import APIRouter

from telegram_bot.notifier import TelegramNotifier

router = APIRouter(prefix="/api/telegram", tags=["telegram"])
TEST_TELEGRAM_MESSAGE = "SportsHunter AI 测试消息"


@router.post("/test")
async def telegram_test() -> dict:
    sent = await TelegramNotifier().send_message(TEST_TELEGRAM_MESSAGE)
    return {"success": bool(sent), "sent": bool(sent)}
