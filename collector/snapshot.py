from __future__ import annotations

from collector.models import CollectionStage


def stage_for_status(status: str) -> CollectionStage:
    if status == "live":
        return CollectionStage.LIVE
    if status == "finished":
        return CollectionStage.POST_MATCH
    return CollectionStage.PRE_MATCH
