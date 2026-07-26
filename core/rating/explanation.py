from __future__ import annotations

from core.rating.scorer import ModuleScore


class ExplanationGenerator:
    def generate(self, module_scores: list[ModuleScore], score: float) -> str:
        strengths = sorted(module_scores, key=lambda item: item.contribution, reverse=True)[:4]
        reasons = []
        for item in strengths:
            if item.name == "team_strength":
                reasons.append("Team strength is above the model baseline")
            elif item.name == "recent_form":
                reasons.append("Recent form supports the preferred side")
            elif item.name == "attack":
                reasons.append("Attack index is materially stronger")
            elif item.name == "home_advantage":
                reasons.append("Home advantage is positive")
            elif item.name == "odds_movement":
                reasons.append("Odds movement does not contradict the signal")
            elif item.name == "injury":
                reasons.append("Injury risk is low")
            else:
                reasons.append(f"{item.name.replace('_', ' ').title()} contributes positively")
        if score >= 85:
            reasons.append("Overall Hunter Score clears the recommendation threshold")
        return "; ".join(reasons) + "."
