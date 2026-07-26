from __future__ import annotations

from pipeline.runner import PredictionPipeline


def run_today() -> list[dict]:
    return [result.to_dict() for result in PredictionPipeline().run_today()]
