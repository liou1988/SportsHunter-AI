from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from datahub.hub import DataHub, build_datahub
from datahub.models import Fixture
from telegram_bot.notifier import TelegramNotifier, TelegramSendResult


FIXTURE_STATUS_LABELS = {
    "scheduled": "未开赛",
    "live": "进行中",
    "finished": "已结束",
    "postponed": "已延期",
    "cancelled": "已取消",
    "unknown": "未知",
}

LEAGUE_LABELS = {
    "eng.1": "英格兰超级联赛",
    "esp.1": "西班牙甲级联赛",
    "ita.1": "意大利甲级联赛",
    "ger.1": "德国甲级联赛",
    "fra.1": "法国甲级联赛",
    "por.1": "葡萄牙超级联赛",
    "ned.1": "荷兰甲级联赛",
    "uefa.champions": "欧洲冠军联赛",
    "uefa.champions_qual": "欧洲冠军联赛资格赛",
    "uefa.europa": "欧足联欧洲联赛",
    "uefa.europa_qual": "欧足联欧洲联赛资格赛",
    "uefa.europa.conf": "欧足联欧洲协会联赛",
    "uefa.europa.conf_qual": "欧足联欧洲协会联赛资格赛",
    "uefa.super_cup": "欧洲超级杯",
    "uefa.nations": "欧洲国家联赛",
    "uefa.euro": "欧洲杯",
    "uefa.euroq": "欧洲杯预选赛",
    "fifa.world": "世界杯",
    "fifa.worldq.uefa": "世界杯欧洲区预选赛",
    "fifa.friendly": "国际友谊赛",
    "fifa.friendly_u21": "U21 国际友谊赛",
    "kor.1": "韩国 K1 联赛",
    "kor.2": "韩国 K2 联赛",
    "jpn.1": "日本 J1 联赛",
    "jpn.2": "日本 J2 联赛",
    "aus.1": "澳大利亚 A 联赛",
    "bra.1": "巴西甲级联赛",
    "bra.2": "巴西乙级联赛",
    "arg.1": "阿根廷甲级联赛",
    "arg.2": "阿根廷乙级联赛",
    "usa.1": "美国职业足球大联盟",
    "mex.1": "墨西哥甲级联赛",
    "mex.2": "墨西哥乙级联赛",
}


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
        league_name = LEAGUE_LABELS.get(fixture.league.id, fixture.league.name)
        status = FIXTURE_STATUS_LABELS.get(fixture.status.value, fixture.status.value)
        lines.extend(
            [
                f"{index}. {fixture.home_team.name} 对阵 {fixture.away_team.name}",
                f"联赛：{league_name}（{fixture.league.id}）",
                f"开赛时间：{_format_beijing_time(fixture.start_time)}",
                f"比赛状态：{status}",
                "",
            ]
        )
    return "\n".join(lines).strip()


def _format_beijing_time(value: datetime) -> str:
    return f"{value.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M')} 北京时间"
