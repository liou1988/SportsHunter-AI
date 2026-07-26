from __future__ import annotations

from fastapi import APIRouter

from telegram_bot.recommendations import RecommendationTelegramPusher

router = APIRouter(prefix="/api/telegram", tags=["telegram"])


@router.post("/test")
async def telegram_test() -> dict:
    result = await RecommendationTelegramPusher().send_test_message()
    return result.to_dict()
