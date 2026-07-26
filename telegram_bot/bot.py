from __future__ import annotations

import asyncio

from telegram_bot.recommendations import RecommendationTelegramPusher


async def main() -> None:
    await RecommendationTelegramPusher().push_today()


if __name__ == "__main__":
    asyncio.run(main())
