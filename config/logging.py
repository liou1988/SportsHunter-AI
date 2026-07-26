from __future__ import annotations

import logging
import sys

from config.settings import Settings, get_settings


def configure_logging(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    settings.ensure_runtime_dirs()

    root = logging.getLogger()
    if root.handlers:
        for handler in root.handlers:
            handler.setLevel(settings.log_level.upper())
        root.setLevel(settings.log_level.upper())
        return

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(settings.log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    root.setLevel(settings.log_level.upper())
    root.addHandler(stream_handler)
    root.addHandler(file_handler)
