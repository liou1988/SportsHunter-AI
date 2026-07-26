from __future__ import annotations

import asyncio

from pipeline.runner import PredictionPipeline
from telegram_bot.notifier import TelegramNotifier


async def main() -> None:
    notifier = TelegramNotifier()
    for result in PredictionPipeline().run_today():
        await notifier.send_prediction(result)


if __name__ == "__main__":
    asyncio.run(main())
