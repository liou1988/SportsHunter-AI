from __future__ import annotations

import asyncio
import json

from telegram_bot.alerts import RecommendationAlertPusher


async def main() -> None:
    result = await RecommendationAlertPusher().push_new()
    print(json.dumps(result.to_dict(), ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
