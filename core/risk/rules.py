RISK_RULES = {
    "red_cards": {"weight": 14.0, "threshold": 1, "reason": "红牌影响已触发"},
    "injuries": {"weight": 12.0, "threshold": 45, "reason": "伤停指数偏高"},
    "odds_anomaly": {"weight": 12.0, "threshold": 85, "reason": "盘口或赔率存在异常"},
    "odds_volatility": {"weight": 10.0, "threshold": 80, "reason": "赔率波动过快"},
    "data_missing": {"weight": 14.0, "threshold": 1, "reason": "关键数据缺失"},
    "league_reliability": {"weight": 8.0, "threshold": 45, "reason": "联赛可信度偏低"},
    "time_anomaly": {"weight": 6.0, "threshold": 90, "reason": "比赛时间存在异常"},
    "market_heat": {"weight": 8.0, "threshold": 82, "reason": "市场热度过高"},
    "live_momentum": {"weight": 8.0, "threshold": 88, "reason": "实时动量异常"},
    "provider_anomaly": {"weight": 8.0, "threshold": 1, "reason": "数据源返回异常数据"},
}
