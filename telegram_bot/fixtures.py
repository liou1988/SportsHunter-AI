from __future__ import annotations

from dataclasses import dataclass

from datahub.hub import DataHub, build_datahub
from datahub.models import Fixture
from telegram_bot.localization import (
    format_beijing_time,
    translate_fixture_status,
    translate_league,
    translate_team_name,
)
from telegram_bot.notifier import TelegramNotifier, TelegramSendResult


@dataclass(slots=True)
class FixtureTelegramPushResult:
    sent: bool
    count: int
    message: str
    success: bool | None = None
    error: str | None = None
    error_code: str | None = None
    message_id: int | None = None

    def to_dict(self) -> dict:
        return {
            "success": self.sent if self.success is None else self.success,
            "sent": self.sent,
            "count": self.count,
            "message": self.message,
            "error": self.error,
            "error_code": self.error_code,
            "message_id": self.message_id,
        }


class TodayFixtureTelegramPusher:
    def __init__(
        self,
        datahub: DataHub | None = None,
        notifier: TelegramNotifier | None = None,
    ) -> None:
        self.datahub = datahub or build_datahub()
        self.notifier = notifier or TelegramNotifier()

    async def push_today(self) -> FixtureTelegramPushResult:
        fixtures = self.datahub.get_today_fixtures()
        message = format_fixtures_message(fixtures)
        send_result = await _send_with_result(self.notifier, message)
        return FixtureTelegramPushResult(
            success=send_result.success,
            sent=send_result.sent,
            count=len(fixtures),
            message=message,
            error=send_result.error,
            error_code=send_result.error_code,
            message_id=send_result.message_id,
        )


async def _send_with_result(notifier: TelegramNotifier, message: str) -> TelegramSendResult:
    sender = getattr(notifier, "send_message_with_result", None)
    if callable(sender):
        return await sender(message)
    sent = await notifier.send_message(message)
    return TelegramSendResult(success=sent, sent=sent)


def format_fixtures_message(fixtures: list[Fixture]) -> str:
    lines = ["SportsHunter AI 今日真实赛程", f"比赛数量：{len(fixtures)}", ""]
    if not fixtures:
        lines.append("今日暂无真实赛程。")
        return "\n".join(lines)

    for index, fixture in enumerate(fixtures, start=1):
        home_team = translate_team_name(fixture.home_team.name)
        away_team = translate_team_name(fixture.away_team.name)
        league_name = translate_league(fixture.league.id, fixture.league.name)
        status = translate_fixture_status(fixture.status.value)
        lines.extend(
            [
                f"{index}. {home_team} 对阵 {away_team}",
                f"联赛：{league_name}（{fixture.league.id}）",
                f"开赛时间：{format_beijing_time(fixture.start_time)}",
                f"比赛状态：{status}",
                "",
            ]
        )
    return "\n".join(lines).strip()
