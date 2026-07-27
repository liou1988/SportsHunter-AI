from __future__ import annotations

import json
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from api.services.recommendations import build_today_recommendations
from config.logging import configure_logging
from config.settings import Settings, get_settings
from datahub.hub import build_datahub
from evaluation.runner import EvaluationRunner
from pipeline.runner import PredictionPipeline
from telegram_bot.alerts import AlertPushResult, RecommendationAlertPusher
from telegram_bot.fixtures import format_fixtures_message
from telegram_bot.notifier import TelegramNotifier, TelegramSendResult
from telegram_bot.recommendations import format_recommendations_message

logger = logging.getLogger(__name__)
MAX_TELEGRAM_TEXT_LENGTH = 3500


def command_help_text() -> str:
    return "\n".join(
        [
            "SportsHunter AI 命令中心",
            "",
            "/status 查看系统与 Telegram 配置状态",
            "/today 获取今日真实赛程",
            "/recommendations 获取今日推荐",
            "/alerts 立即检查并推送新机会",
            "/report 生成并查看自动复盘日报",
            "/help 查看命令列表",
        ]
    )


def format_status_message(health: dict) -> str:
    config = health.get("config") or {}
    warnings = config.get("warnings") or []
    lines = [
        "SportsHunter AI 状态",
        "",
        f"Telegram：{health.get('health', '-')}",
        f"启用：{config.get('enabled', False)}",
        f"配置就绪：{config.get('ready', False)}",
        f"Bot Token：{'已配置' if config.get('bot_token_configured') else '未配置'}",
        f"Chat ID：{'已配置' if config.get('chat_id_configured') else '未配置'}",
    ]
    if health.get("error"):
        lines.append(f"错误：{health['error']}")
    if warnings:
        lines.append("")
        lines.append("提醒：")
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines)


def format_alert_push_reply(result: AlertPushResult | dict) -> str:
    payload = result.to_dict() if hasattr(result, "to_dict") else dict(result)
    return "\n".join(
        [
            "SportsHunter AI 机会检查",
            "",
            f"执行成功：{payload.get('success', False)}",
            f"是否发送：{payload.get('sent', False)}",
            f"评估场次：{payload.get('evaluated_count', 0)}",
            f"符合场次：{payload.get('eligible_count', 0)}",
            f"新推送：{payload.get('pushed_count', 0)}",
            f"已跳过：{payload.get('skipped_count', 0)}",
            f"结果：{payload.get('message') or '-'}",
            f"错误：{payload.get('error') or '-'}",
        ]
    )


def build_application(settings: Settings | None = None) -> Application:
    settings = settings or get_settings()
    bot_token = settings.telegram_effective_bot_token
    if not bot_token:
        raise RuntimeError("缺少 BOT_TOKEN 或 TELEGRAM_BOT_TOKEN，Telegram Bot 无法启动。")

    application = Application.builder().token(bot_token).build()
    application.add_handler(CommandHandler(["start", "help"], help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CommandHandler("recommendations", recommendations_command))
    application.add_handler(CommandHandler(["alerts", "check"], alerts_command))
    application.add_handler(CommandHandler("report", report_command))
    return application


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, command_help_text())


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    health = await TelegramNotifier().health_check()
    await _reply(update, format_status_message(health))


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        fixtures = build_datahub().get_today_fixtures()
        await _reply(update, format_fixtures_message(fixtures))
    except Exception as exc:  # noqa: BLE001 - command handlers should answer in-chat
        logger.exception("telegram /today command failed", exc_info=exc)
        await _reply(update, f"今日赛程获取失败：{exc}")


async def recommendations_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        payload = build_today_recommendations(PredictionPipeline(), include_pass=False)
        await _reply(update, format_recommendations_message(payload))
    except Exception as exc:  # noqa: BLE001
        logger.exception("telegram /recommendations command failed", exc_info=exc)
        await _reply(update, f"今日推荐获取失败：{exc}")


async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        result = await RecommendationAlertPusher().push_new()
        await _reply(update, format_alert_push_reply(result))
    except Exception as exc:  # noqa: BLE001
        logger.exception("telegram /alerts command failed", exc_info=exc)
        await _reply(update, f"机会检查失败：{exc}")


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        report = EvaluationRunner().daily()
        await _reply(update, report.to_markdown())
    except Exception as exc:  # noqa: BLE001
        logger.exception("telegram /report command failed", exc_info=exc)
        await _reply(update, f"复盘日报生成失败：{exc}")


async def _reply(update: Update, text: str) -> None:
    message = update.effective_message
    if message is None:
        return
    for chunk in _chunks(text, MAX_TELEGRAM_TEXT_LENGTH):
        await message.reply_text(chunk)


def _chunks(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        chunk = remaining[:limit]
        split_at = chunk.rfind("\n")
        if split_at > limit * 0.6:
            chunk = chunk[:split_at]
        chunks.append(chunk)
        remaining = remaining[len(chunk) :].lstrip()
    return chunks


def main() -> None:
    configure_logging()
    settings = get_settings()
    status = TelegramNotifier(settings).config_status()
    if not status.bot_token_configured or not status.bot_token_format_valid:
        result = TelegramSendResult(False, False, "Telegram Bot 启动配置不完整。", "CONFIG_NOT_READY", config=status)
        print(json.dumps(result.to_dict(include_config=True), ensure_ascii=False))
        return

    logger.info("telegram command bot starting")
    build_application(settings).run_polling()


if __name__ == "__main__":
    main()
