from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


REQUIRED_FEATURE_NAMES = [
    "home_recent_form",
    "away_recent_form",
    "home_attack_index",
    "away_attack_index",
    "home_defense_index",
    "away_defense_index",
    "elo_difference",
    "odds_move",
    "market_heat",
    "fatigue_index",
    "home_advantage",
    "injury_index",
    "live_momentum",
    "league_strength",
]


@dataclass(slots=True)
class FeatureVector:
    fixture_id: str
    features: dict[str, float]
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "datahub"
    warnings: list[str] = field(default_factory=list)

    def get(self, name: str, default: float = 0.0) -> float:
        value = self.features.get(name, default)
        return float(value if value is not None else default)

    def to_dict(self) -> dict:
        return {
            "fixture_id": self.fixture_id,
            "features": self.features,
            "generated_at": self.generated_at.isoformat(),
            "source": self.source,
            "warnings": self.warnings,
        }
