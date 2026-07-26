from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class SyncSummary:
    sync_type: str
    provider: str
    synced_count: int = 0
    failed_count: int = 0
    status: str = "success"
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    error: str | None = None

    def finish(self) -> "SyncSummary":
        self.finished_at = datetime.now(timezone.utc)
        if self.failed_count and not self.synced_count:
            self.status = "failed"
        elif self.failed_count:
            self.status = "partial"
        return self
