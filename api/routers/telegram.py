from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from api.dependencies import get_datahub, get_prediction_pipeline
from datahub.hub import DataHub
from pipeline.runner import PredictionPipeline
from telegram_bot.fixtures import TodayFixtureTelegramPusher
from telegram_bot.notifier import TelegramNotifier, TelegramSendResult
from telegram_bot.recommendations import RecommendationTelegramPusher

router = APIRouter(prefix="/api/telegram", tags=["telegram"])
TEST_TELEGRAM_MESSAGE = "SportsHunter AI 测试消息"
logger = logging.getLogger(__name__)


@router.get("/status")
async def telegram_status() -> dict:
    return await TelegramNotifier().health_check()


@router.post("/test")
async def telegram_test() -> dict:
    try:
        result = await TelegramNotifier().send_message_with_result(TEST_TELEGRAM_MESSAGE)
    except Exception as exc:  # noqa: BLE001 - never expose Telegram SDK errors as 500
        logger.exception("telegram test endpoint failed", exc_info=True)
        result = TelegramSendResult(False, False, f"Telegram 测试发送异常：{exc}", "INTERNAL_ERROR")
    return _compact_send_response(result)


@router.post("/fixtures/today")
async def telegram_today_fixtures(datahub: DataHub = Depends(get_datahub)) -> dict:
    try:
        result = await TodayFixtureTelegramPusher(datahub=datahub, notifier=TelegramNotifier()).push_today()
    except Exception as exc:  # noqa: BLE001 - provider or telegram errors must not return 500 here
        logger.exception("telegram fixtures endpoint failed", exc_info=True)
        return {"success": False, "sent": False, "count": 0, "message": "", "error": f"今日赛程推送异常：{exc}", "error_code": "INTERNAL_ERROR"}
    return result.to_dict()


@router.post("/recommendations/today")
async def telegram_today_recommendations(pipeline: PredictionPipeline = Depends(get_prediction_pipeline)) -> dict:
    try:
        result = await RecommendationTelegramPusher(pipeline=pipeline, notifier=TelegramNotifier()).push_today()
    except Exception as exc:  # noqa: BLE001 - provider or telegram errors must not return 500 here
        logger.exception("telegram recommendations endpoint failed", exc_info=True)
        return {"success": False, "sent": False, "count": 0, "message": "", "error": f"今日推荐推送异常：{exc}", "error_code": "INTERNAL_ERROR"}
    return result.to_dict()


def _compact_send_response(result: TelegramSendResult) -> dict:
    payload = {"success": result.success, "sent": result.sent}
    if result.error:
        payload["error"] = result.error
        payload["error_code"] = result.error_code
    if result.message_id is not None:
        payload["message_id"] = result.message_id
    return payload
