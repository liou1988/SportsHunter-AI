from __future__ import annotations

from dataclasses import dataclass

from features.models import FeatureVector


@dataclass(slots=True)
class ModuleScore:
    name: str
    raw_score: float
    weight: float

    @property
    def contribution(self) -> float:
        return round(self.raw_score * self.weight / 100, 2)


class HunterScorer:
    def module_scores(self, vector: FeatureVector, weights: dict[str, float]) -> list[ModuleScore]:
        f = vector.get
        raw_scores = {
            "team_strength": f("elo_difference"),
            "recent_form": (f("home_recent_form") + (100 - f("away_recent_form"))) / 2,
            "attack": (f("home_attack_index") + (100 - f("away_defense_index"))) / 2,
            "defense": (f("home_defense_index") + (100 - f("away_attack_index"))) / 2,
            "home_advantage": f("home_advantage"),
            "odds_movement": f("odds_move"),
            "market_heat": 100 - abs(f("market_heat") - 62),
            "league_strength": f("league_strength"),
            "fatigue": 100 - f("fatigue_index"),
            "injury": 100 - f("injury_index"),
            "live_momentum": f("live_momentum"),
        }
        return [
            ModuleScore(name=name, raw_score=_clip(score), weight=weights[name])
            for name, score in raw_scores.items()
        ]


def _clip(value: float) -> float:
    return max(0.0, min(100.0, round(value, 2)))
