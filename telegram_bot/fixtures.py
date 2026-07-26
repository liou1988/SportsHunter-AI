from __future__ import annotations

from dataclasses import dataclass

from datahub.hub import DataHub, build_datahub
from datahub.models import Fixture
from telegram_bot.notifier import TelegramNotifier


@dataclass(slots=True)
class FixtureTelegramPushResult:
    sent: bool
    count: int
    message: str

    def to_dict(self) -> dict:
        return {"sent": self.sent, "count": self.count, "message": self.message}


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
        sent = await self.notifier.send_message(message)
        return FixtureTelegramPushResult(sent=sent, count=len(fixtures), message=message)


def format_fixtures_message(fixtures: list[Fixture]) -> str:
    lines = ["SportsHunter AI Today Real Fixtures", f"Count: {len(fixtures)}", ""]
    if not fixtures:
        lines.append("No real fixtures returned today.")
        return "\n".join(lines)

    for index, fixture in enumerate(fixtures, start=1):
        lines.extend(
            [
                f"{index}. {fixture.home_team.name} vs {fixture.away_team.name}",
                f"League: {fixture.league.name} ({fixture.league.id})",
                f"Kickoff: {fixture.start_time.isoformat()}",
                f"Status: {fixture.status.value}",
                "",
            ]
        )
    return "\n".join(lines).strip()
