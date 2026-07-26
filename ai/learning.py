from __future__ import annotations


class LearningRecorder:
    def record(self, outcome: str, module: str | None = None, notes: str | None = None) -> dict:
        return {"outcome": outcome, "module": module, "notes": notes}
