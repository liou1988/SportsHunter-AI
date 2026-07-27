from __future__ import annotations

from core.rating.scorer import ModuleScore


MODULE_LABELS = {
    "defense": "防守稳定性",
    "market_heat": "市场热度",
    "league_strength": "联赛强度",
    "fatigue": "体能状态",
    "live_momentum": "即时走势",
}


class ExplanationGenerator:
    def generate(self, module_scores: list[ModuleScore], score: float) -> str:
        strengths = sorted(module_scores, key=lambda item: item.contribution, reverse=True)[:4]
        reasons = []
        for item in strengths:
            if item.name == "team_strength":
                reasons.append("球队综合实力高于模型基准")
            elif item.name == "recent_form":
                reasons.append("近期状态支持推荐方向")
            elif item.name == "attack":
                reasons.append("进攻指数具备明显优势")
            elif item.name == "home_advantage":
                reasons.append("主场优势明显")
            elif item.name == "odds_movement":
                reasons.append("赔率走势未与推荐信号冲突")
            elif item.name == "injury":
                reasons.append("伤停风险较低")
            else:
                label = MODULE_LABELS.get(item.name, item.name.replace("_", " "))
                reasons.append(f"{label}对评分有正向贡献")
        if score >= 85:
            reasons.append("综合猎手评分达到推荐阈值")
        return "；".join(reasons) + "。"
