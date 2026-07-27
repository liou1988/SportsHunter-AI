from __future__ import annotations

import logging
import re
import sys
from typing import Any

from config.settings import Settings, get_settings


TELEGRAM_BOT_TOKEN_PATTERN = re.compile(r"bot\d+:[A-Za-z0-9_-]+")


def _redact_sensitive_value(value: Any) -> Any:
    if isinstance(value, str):
        return TELEGRAM_BOT_TOKEN_PATTERN.sub("bot<redacted>", value)
    if isinstance(value, tuple):
        return tuple(_redact_sensitive_value(item) for item in value)
    if isinstance(value, list):
        return [_redact_sensitive_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_sensitive_value(item) for key, item in value.items()}
    rendered = _render_if_sensitive(value)
    if rendered is not None:
        return rendered
    return value


def _render_if_sensitive(value: Any) -> str | None:
    try:
        rendered = str(value)
    except Exception:  # noqa: BLE001 - logging filters must never break log emission
        return None
    if TELEGRAM_BOT_TOKEN_PATTERN.search(rendered):
        return TELEGRAM_BOT_TOKEN_PATTERN.sub("bot<redacted>", rendered)
    return None


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact_sensitive_value(record.msg)
        record.args = _redact_sensitive_value(record.args)
        return True


def configure_logging(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    settings.ensure_runtime_dirs()

    root = logging.getLogger()
    sensitive_filter = SensitiveDataFilter()
    _attach_sensitive_filter(sensitive_filter)
    if root.handlers:
        for handler in root.handlers:
            handler.setLevel(settings.log_level.upper())
            if not any(isinstance(item, SensitiveDataFilter) for item in handler.filters):
                handler.addFilter(sensitive_filter)
        root.setLevel(settings.log_level.upper())
        return

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(sensitive_filter)

    file_handler = logging.FileHandler(settings.log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(sensitive_filter)

    root.setLevel(settings.log_level.upper())
    root.addHandler(stream_handler)
    root.addHandler(file_handler)


def _attach_sensitive_filter(sensitive_filter: SensitiveDataFilter) -> None:
    for logger_name in ("httpx", "httpcore", "telegram", "telegram.ext"):
        logger = logging.getLogger(logger_name)
        if not any(isinstance(item, SensitiveDataFilter) for item in logger.filters):
            logger.addFilter(sensitive_filter)
