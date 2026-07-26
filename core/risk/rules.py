RISK_RULES = {
    "red_cards": {"weight": 14.0, "threshold": 1, "reason": "Red card impact detected"},
    "injuries": {"weight": 12.0, "threshold": 45, "reason": "Injury index is elevated"},
    "odds_anomaly": {"weight": 12.0, "threshold": 85, "reason": "Odds anomaly detected"},
    "odds_volatility": {"weight": 10.0, "threshold": 80, "reason": "Odds moved too quickly"},
    "data_missing": {"weight": 14.0, "threshold": 1, "reason": "Required provider data is missing"},
    "league_reliability": {"weight": 8.0, "threshold": 45, "reason": "League reliability is low"},
    "time_anomaly": {"weight": 6.0, "threshold": 90, "reason": "Match time looks abnormal"},
    "market_heat": {"weight": 8.0, "threshold": 82, "reason": "Market is overheated"},
    "live_momentum": {"weight": 8.0, "threshold": 88, "reason": "Live momentum is abnormal"},
    "provider_anomaly": {"weight": 8.0, "threshold": 1, "reason": "Provider returned anomalous data"},
}
