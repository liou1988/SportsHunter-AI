from __future__ import annotations

import asyncio
import json

from telegram_bot.recommendations import RecommendationTelegramPusher


async def main() -> None:
    result = await RecommendationTelegramPusher().push_today()
    print(json.dumps(result.to_dict(), ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
