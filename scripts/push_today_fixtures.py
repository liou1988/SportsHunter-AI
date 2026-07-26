from __future__ import annotations

import asyncio
import json

from telegram_bot.fixtures import TodayFixtureTelegramPusher


async def main() -> None:
    result = await TodayFixtureTelegramPusher().push_today()
    print(json.dumps({"success": result.sent, **result.to_dict()}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
