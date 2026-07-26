from __future__ import annotations


class EvaluationAnalyzer:
    def explain(self, row: dict) -> str:
        if row.get("won"):
            return "Won because rating, risk and market signal aligned."
        return "Lost because at least one module overestimated edge or missed match context."

    def module_notes(self, rows: list[dict]) -> list[str]:
        if not rows:
            return ["No settled predictions available."]
        return ["Review modules with the largest losing contribution before changing weights."]
