from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ValidationFailure:
    fixture_id: str
    error: str


@dataclass(slots=True)
class ValidationReport:
    fixture_count: int
    success_count: int
    failure_count: int
    provider_status: str
    hunter_scores: list[float] = field(default_factory=list)
    risks: dict[str, int] = field(default_factory=dict)
    signals: dict[str, int] = field(default_factory=dict)
    failures: list[ValidationFailure] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            "# SportsHunter-AI Validation Report",
            "",
            f"- Fixtures: {self.fixture_count}",
            f"- Success: {self.success_count}",
            f"- Failed: {self.failure_count}",
            f"- Provider: {self.provider_status}",
            "",
            "## HunterScore Distribution",
            f"- Scores: {self.hunter_scores}",
            "",
            "## Risk Distribution",
        ]
        lines.extend(f"- {key}: {value}" for key, value in self.risks.items())
        lines.append("")
        lines.append("## Signal Distribution")
        lines.extend(f"- {key}: {value}" for key, value in self.signals.items())
        lines.append("")
        lines.append("## Exceptions")
        if self.failures:
            lines.extend(f"- {item.fixture_id}: {item.error}" for item in self.failures)
        else:
            lines.append("- None")
        return "\n".join(lines) + "\n"
