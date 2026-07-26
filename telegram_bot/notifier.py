from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from telegram import Bot
from telegram.error import BadRequest, Forbidden, InvalidToken, NetworkError, TelegramError, TimedOut

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

BOT_TOKEN_PATTERN = re.compile(r"^\d+:[A-Za-z0-9_-]{20,}$")


@dataclass(slots=True)
class TelegramConfigStatus:
    enabled: bool
    telegram_enabled: bool
    telegram_push_enabled: bool
    bot_token_configured: bool
    bot_token_format_valid: bool
    bot_token_length: int
    chat_id_configured: bool
    chat_id_type: str
    ready: bool
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "telegram_enabled": self.telegram_enabled,
            "telegram_push_enabled": self.telegram_push_enabled,
            "bot_token_configured": self.bot_token_configured,
            "bot_token_format_valid": self.bot_token_format_valid,
            "bot_token_length": self.bot_token_length,
            "chat_id_configured": self.chat_id_configured,
            "chat_id_type": self.chat_id_type,
            "ready": self.ready,
            "warnings": self.warnings,
        }


@dataclass(slots=True)
class TelegramSendResult:
    success: bool
    sent: bool
    error: str | None = None
    error_code: str | None = None
    message_id: int | None = None
    bot_username: str | None = None
    config: TelegramConfigStatus | None = None

    def to_dict(self, include_config: bool = False) -> dict:
        payload = {
            "success": self.success,
            "sent": self.sent,
            "error": self.error,
            "error_code": self.error_code,
            "message_id": self.message_id,
            "bot_username": self.bot_username,
        }
        if include_config and self.config is not None:
            payload["config"] = self.config.to_dict()
        return payload


class TelegramNotifier:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def config_status(self) -> TelegramConfigStatus:
        bot_token = self.settings.telegram_effective_bot_token or ""
        chat_id = self.settings.telegram_effective_chat_id or ""
        warnings: list[str] = []
        token_configured = bool(bot_token)
        token_valid = bool(BOT_TOKEN_PATTERN.match(bot_token))
        chat_configured = bool(chat_id)
        enabled = self.settings.telegram_is_enabled

        if not enabled:
            warnings.append("Telegram 未启用，请设置 TELEGRAM_ENABLED=true 或 TELEGRAM_PUSH_ENABLED=true。")
        if not token_configured:
            warnings.append("缺少 BOT_TOKEN 或 TELEGRAM_BOT_TOKEN。")
        elif not token_valid:
            warnings.append("Bot Token 格式异常，应类似 123456:ABCDEF。")
        if not chat_configured:
            warnings.append("缺少 CHAT_ID 或 TELEGRAM_CHAT_ID。")
        elif self._chat_id_matches_bot_id(chat_id, bot_token):
            warnings.append("CHAT_ID 不能填写机器人自身 ID，请填写用户、群组或频道的 chat id。")

        return TelegramConfigStatus(
            enabled=enabled,
            telegram_enabled=self.settings.telegram_enabled,
            telegram_push_enabled=self.settings.telegram_push_enabled,
            bot_token_configured=token_configured,
            bot_token_format_valid=token_valid,
            bot_token_length=len(bot_token),
            chat_id_configured=chat_configured,
            chat_id_type=self._chat_id_type(chat_id),
            ready=enabled and token_configured and token_valid and chat_configured and not self._chat_id_matches_bot_id(chat_id, bot_token),
            warnings=warnings,
        )

    async def health_check(self) -> dict:
        status = self.config_status()
        payload = {
            "provider": "telegram",
            "health": "ok" if status.ready else "not_ready",
            "config": status.to_dict(),
            "bot": {},
            "chat": {},
            "error": None,
            "error_code": None,
        }
        if not status.ready:
            payload["error"] = "；".join(status.warnings)
            payload["error_code"] = "CONFIG_NOT_READY"
            return payload

        bot_token = self.settings.telegram_effective_bot_token
        chat_id = self.settings.telegram_effective_chat_id
        try:
            bot = Bot(bot_token)
            bot_user = await bot.get_me()
            if self._chat_id_matches_bot_id(str(chat_id), str(bot_token)):
                payload["health"] = "not_ready"
                payload["error"] = "CHAT_ID 不能填写机器人自身 ID。"
                payload["error_code"] = "CHAT_ID_IS_BOT_ID"
                return payload
            chat = await bot.get_chat(chat_id=chat_id)
            payload["bot"] = {"id": bot_user.id, "username": bot_user.username}
            payload["chat"] = {"type": chat.type}
            return payload
        except Exception as exc:  # noqa: BLE001 - diagnostic endpoint must return structured errors
            result = self._error_result(exc, status)
            payload["health"] = "down"
            payload["error"] = result.error
            payload["error_code"] = result.error_code
            return payload

    async def send_message(self, text: str) -> bool:
        return (await self.send_message_with_result(text)).sent

    async def send_message_with_result(self, text: str) -> TelegramSendResult:
        status = self.config_status()
        if not status.ready:
            logger.warning("telegram config is not ready: %s", "；".join(status.warnings))
            return TelegramSendResult(
                success=False,
                sent=False,
                error="；".join(status.warnings),
                error_code="CONFIG_NOT_READY",
                config=status,
            )

        bot_token = self.settings.telegram_effective_bot_token
        chat_id = self.settings.telegram_effective_chat_id
        try:
            bot = Bot(bot_token)
            sent_message = await bot.send_message(chat_id=chat_id, text=text)
            return TelegramSendResult(
                success=True,
                sent=True,
                message_id=getattr(sent_message, "message_id", None),
                config=status,
            )
        except Exception as exc:  # noqa: BLE001 - Telegram endpoints must not crash API routes
            logger.exception("telegram send failed", exc_info=exc)
            return self._error_result(exc, status)

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

    @staticmethod
    def _chat_id_type(chat_id: str) -> str:
        if not chat_id:
            return "missing"
        if chat_id.startswith("@"):
            return "channel_or_username"
        if chat_id.startswith("-100"):
            return "supergroup_or_channel"
        if chat_id.startswith("-"):
            return "group"
        if chat_id.isdigit():
            return "private_or_bot_id"
        return "unknown"

    @staticmethod
    def _chat_id_matches_bot_id(chat_id: str, bot_token: str) -> bool:
        if not chat_id or not bot_token or ":" not in bot_token:
            return False
        bot_id = bot_token.split(":", 1)[0]
        return chat_id == bot_id

    @staticmethod
    def _error_result(exc: Exception, status: TelegramConfigStatus | None = None) -> TelegramSendResult:
        message = str(exc)
        if isinstance(exc, InvalidToken):
            return TelegramSendResult(False, False, "BOT_TOKEN 无效，请到 BotFather 重新生成。", "INVALID_TOKEN", config=status)
        if isinstance(exc, Forbidden):
            if "can't send messages to the bot" in message:
                return TelegramSendResult(False, False, "CHAT_ID 配成了机器人自身 ID，机器人不能给机器人发消息。", "CHAT_ID_IS_BOT_ID", config=status)
            return TelegramSendResult(False, False, "机器人没有权限向该 Chat 发送消息，请确认已对 Bot 发送 /start 或已把 Bot 加入群/频道。", "FORBIDDEN", config=status)
        if isinstance(exc, BadRequest):
            return TelegramSendResult(False, False, f"Telegram 请求参数错误：{message}", "BAD_REQUEST", config=status)
        if isinstance(exc, TimedOut):
            return TelegramSendResult(False, False, "Telegram 请求超时，请稍后重试。", "TIMEOUT", config=status)
        if isinstance(exc, NetworkError):
            return TelegramSendResult(False, False, f"Telegram 网络异常：{message}", "NETWORK_ERROR", config=status)
        if isinstance(exc, TelegramError):
            return TelegramSendResult(False, False, f"Telegram 返回错误：{message}", "TELEGRAM_ERROR", config=status)
        return TelegramSendResult(False, False, f"Telegram 发送异常：{message}", "UNKNOWN_ERROR", config=status)
