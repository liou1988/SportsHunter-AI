from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


class CollectionStage(StrEnum):
    PRE_MATCH = "pre_match"
    LIVE = "live"
    POST_MATCH = "post_match"


@dataclass(slots=True)
class CollectionSummary:
    stage: CollectionStage
    collected_count: int
    failed_count: int = 0
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
