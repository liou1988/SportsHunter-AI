from __future__ import annotations

from validation.runner import ValidationRunner


def run_validation() -> str:
    return ValidationRunner().run().to_markdown()
