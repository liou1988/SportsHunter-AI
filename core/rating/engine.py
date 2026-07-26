from __future__ import annotations

from dataclasses import dataclass

from core.rating.explanation import ExplanationGenerator
from core.rating.scorer import HunterScorer, ModuleScore
from core.rating.weights import RATING_WEIGHTS
from features.models import REQUIRED_FEATURE_NAMES, FeatureVector


@dataclass(slots=True)
class HunterScoreBreakdown:
    modules: dict[str, float]

    def to_dict(self) -> dict:
        return {"modules": self.modules}


@dataclass(slots=True)
class HunterScore:
    score: float
    grade: str
    confidence: float
    breakdown: HunterScoreBreakdown
    explanation: str

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "grade": self.grade,
            "confidence": self.confidence,
            "breakdown": self.breakdown.to_dict(),
            "explanation": self.explanation,
        }


class HunterRatingEngine:
    def __init__(
        self,
        weights: dict[str, float] | None = None,
        scorer: HunterScorer | None = None,
        explanation: ExplanationGenerator | None = None,
    ) -> None:
        self.weights = weights or RATING_WEIGHTS.copy()
        self.scorer = scorer or HunterScorer()
        self.explanation = explanation or ExplanationGenerator()

    def score(self, vector: FeatureVector) -> HunterScore:
        module_scores = self.scorer.module_scores(vector, self.weights)
        total_weight = sum(item.weight for item in module_scores) or 1
        score = round(sum(item.contribution for item in module_scores) * 100 / total_weight, 2)
        confidence = self._confidence(vector, module_scores)
        breakdown = HunterScoreBreakdown(modules={item.name: item.contribution for item in module_scores})
        return HunterScore(
            score=score,
            grade=self._grade(score),
            confidence=confidence,
            breakdown=breakdown,
            explanation=self.explanation.generate(module_scores, score),
        )

    @staticmethod
    def _confidence(vector: FeatureVector, module_scores: list[ModuleScore]) -> float:
        missing_penalty = len(vector.warnings) * 0.08
        populated = sum(1 for name in REQUIRED_FEATURE_NAMES if vector.get(name, 0) > 0)
        completeness = populated / len(REQUIRED_FEATURE_NAMES)
        stability = 1 - min(0.25, abs(50 - sum(item.raw_score for item in module_scores) / len(module_scores)) / 200)
        return round(max(0.0, min(1.0, completeness * stability - missing_penalty)), 2)

    @staticmethod
    def _grade(score: float) -> str:
        if score >= 90:
            return "★★★★★"
        if score >= 85:
            return "★★★★☆"
        if score >= 75:
            return "★★★☆☆"
        if score >= 65:
            return "★★☆☆☆"
        return "★☆☆☆☆"
