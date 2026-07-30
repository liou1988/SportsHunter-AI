from __future__ import annotations

from dataclasses import dataclass

from datahub.hub import DataHub
from datahub.models import FixtureStatus, OddsMarket, Statistics
from features.models import REQUIRED_FEATURE_NAMES, FeatureVector


class FeatureCache:
    def __init__(self) -> None:
        self._items: dict[str, FeatureVector] = {}

    def get(self, fixture_id: str) -> FeatureVector | None:
        return self._items.get(fixture_id)

    def set(self, vector: FeatureVector) -> FeatureVector:
        self._items[vector.fixture_id] = vector
        return vector


class FeatureValidator:
    def validate(self, vector: FeatureVector) -> FeatureVector:
        missing = [name for name in REQUIRED_FEATURE_NAMES if name not in vector.features]
        if missing:
            raise ValueError(f"missing required features: {', '.join(missing)}")
        vector.features = {name: _clip(float(value)) for name, value in vector.features.items()}
        return vector


@dataclass
class FeatureBuilder:
    datahub: DataHub

    def build(self, fixture_id: str) -> FeatureVector:
        fixture = self.datahub.get_fixture(fixture_id)
        warnings: list[str] = []
        try:
            odds = self.datahub.get_odds(fixture_id)
        except Exception:  # noqa: BLE001 - provider boundary is recorded as feature warning
            odds = []
            warnings.append("odds_unavailable")
        try:
            statistics = self.datahub.get_statistics(fixture_id)
        except Exception:  # noqa: BLE001 - free feeds often omit pre-match statistics
            statistics = Statistics(fixture_id=fixture_id, provider=fixture.provider)
            warnings.append("statistics_unavailable")

        stats_available = any(
            value is not None
            for value in [
                statistics.home_shots,
                statistics.away_shots,
                statistics.home_shots_on_target,
                statistics.away_shots_on_target,
            ]
        )
        home_shots = statistics.home_shots or 0
        away_shots = statistics.away_shots or 0
        home_target = statistics.home_shots_on_target or 0
        away_target = statistics.away_shots_on_target or 0
        home_red = statistics.home_red_cards or 0
        away_red = statistics.away_red_cards or 0

        european = next((item for item in odds if item.market == OddsMarket.EUROPEAN), None)
        if european is None:
            warnings.append("odds_missing")

        home_odds = european.home if european else None
        away_odds = european.away if european else None
        market_heat = _market_heat(home_odds, away_odds)
        odds_move = 52.0 if european else 50.0
        league_strength = 75.0 if fixture.league.id in {"eng.1", "esp.1", "ita.1", "ger.1"} else 62.0

        if stats_available:
            home_recent_form = _clip(52 + home_target * 4 - away_target * 2)
            away_recent_form = _clip(52 + away_target * 4 - home_target * 2)
            home_attack_index = _clip(50 + home_shots * 2 + home_target * 3)
            away_attack_index = _clip(50 + away_shots * 2 + away_target * 3)
            home_defense_index = _clip(58 - away_target * 5 - away_shots + away_red * 4)
            away_defense_index = _clip(58 - home_target * 5 - home_shots + home_red * 4)
            home_advantage = 58.0
        else:
            home_recent_form = 50.0
            away_recent_form = 50.0
            home_attack_index = 50.0
            away_attack_index = 50.0
            home_defense_index = 50.0
            away_defense_index = 50.0
            home_advantage = 56.0

        features = {
            "home_recent_form": home_recent_form,
            "away_recent_form": away_recent_form,
            "home_attack_index": home_attack_index,
            "away_attack_index": away_attack_index,
            "home_defense_index": home_defense_index,
            "away_defense_index": away_defense_index,
            "elo_difference": _clip(50 + (market_heat - 50) / 3),
            "odds_move": odds_move,
            "market_heat": market_heat,
            "fatigue_index": 22.0,
            "home_advantage": home_advantage,
            "injury_index": 5.0,
            "live_momentum": _live_momentum(fixture.status, home_target, away_target) if stats_available else 50.0,
            "league_strength": league_strength,
        }
        return FeatureVector(fixture_id=fixture_id, features=features, warnings=warnings)


class FeaturePipeline:
    def __init__(
        self,
        builder: FeatureBuilder,
        validator: FeatureValidator | None = None,
        cache: FeatureCache | None = None,
    ) -> None:
        self.builder = builder
        self.validator = validator or FeatureValidator()
        self.cache = cache or FeatureCache()

    def build(self, fixture_id: str, refresh: bool = False) -> FeatureVector:
        cached = None if refresh else self.cache.get(fixture_id)
        if cached is not None:
            return cached
        vector = self.validator.validate(self.builder.build(fixture_id))
        return self.cache.set(vector)


def _market_heat(home_odds: float | None, away_odds: float | None) -> float:
    if home_odds is None or away_odds is None or home_odds <= 0 or away_odds <= 0:
        return 50.0
    home_probability = (1 / home_odds) / ((1 / home_odds) + (1 / away_odds))
    return _clip(50 + (home_probability - 0.5) * 80)


def _live_momentum(status: FixtureStatus, home_target: int, away_target: int) -> float:
    if status != FixtureStatus.LIVE:
        return 50.0
    return _clip(50 + (home_target - away_target) * 8)


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, round(value, 2)))
