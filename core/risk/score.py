from __future__ import annotations

from features.models import FeatureVector


def compute_risk_inputs(vector: FeatureVector) -> dict[str, float]:
    return {
        "red_cards": 0.0,
        "injuries": vector.get("injury_index"),
        "odds_anomaly": max(0.0, abs(vector.get("odds_move") - 50) * 1.5),
        "odds_volatility": max(0.0, abs(vector.get("odds_move") - 50)),
        "data_missing": float(len(vector.warnings)),
        "league_reliability": 100 - vector.get("league_strength"),
        "time_anomaly": 0.0,
        "market_heat": vector.get("market_heat"),
        "live_momentum": max(0.0, abs(vector.get("live_momentum") - 50) * 1.7),
        "provider_anomaly": 1.0 if "provider_error" in vector.warnings else 0.0,
    }
