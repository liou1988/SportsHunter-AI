from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from api.dependencies import get_datahub
from datahub.hub import DataHub
from telegram_bot.fixtures import TodayFixtureTelegramPusher
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


@router.post("/fixtures/today")
async def telegram_today_fixtures(datahub: DataHub = Depends(get_datahub)) -> dict:
    try:
        result = await TodayFixtureTelegramPusher(datahub=datahub, notifier=TelegramNotifier()).push_today()
    except Exception as exc:  # noqa: BLE001 - provider or telegram errors must not return 500 here
        logger.exception("telegram fixtures endpoint failed", exc_info=exc)
        return {"success": False, "sent": False, "count": 0, "message": ""}
    return {"success": bool(result.sent), **result.to_dict()}
