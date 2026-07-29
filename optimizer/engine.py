from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from core.rating.weights import RATING_WEIGHTS
from database import models as orm
from database.repositories import SportsRepository
from database.session import SessionLocal
from evaluation.dataset import EvaluationDataset
from evaluation.metrics import calculate_metrics
from optimizer.models import OptimizerReport, WeightAdjustmentSuggestion
from optimizer.weights import load_active_rating_weights

SessionFactory = Callable[[], Session]

MIN_WEIGHT = 2.0
MAX_DELTA_PER_MODULE = 1.2
MIN_RECOMMENDED_SAMPLE = 20

MODULE_LABELS = {
    "team_strength": "球队实力",
    "recent_form": "近期状态",
    "attack": "进攻指数",
    "defense": "防守指数",
    "home_advantage": "主场优势",
    "odds_movement": "赔率变化",
    "market_heat": "市场热度",
    "league_strength": "联赛强度",
    "fatigue": "体能疲劳",
    "injury": "伤停风险",
    "live_momentum": "滚球动能",
}

ERROR_IMPACTS = {
    "score_projection": {"attack": -0.45, "defense": -0.45, "team_strength": -0.3},
    "totals_market": {"odds_movement": -0.55, "market_heat": -0.45, "attack": -0.2},
    "handicap_market": {"team_strength": -0.45, "home_advantage": -0.35, "odds_movement": -0.25},
    "signal": {"market_heat": -0.35, "odds_movement": -0.35, "live_momentum": -0.2},
    "unknown": {},
}

REDISTRIBUTION_TARGETS = ("recent_form", "league_strength", "defense", "team_strength")


class ModelOptimizer:
    def __init__(
        self,
        dataset: EvaluationDataset | None = None,
        session_factory: SessionFactory = SessionLocal,
        min_recommended_sample: int = MIN_RECOMMENDED_SAMPLE,
    ) -> None:
        self.session_factory = session_factory
        self.dataset = dataset or EvaluationDataset(session_factory=session_factory)
        self.min_recommended_sample = min_recommended_sample

    def build_report(self, period: str = "monthly") -> OptimizerReport:
        current_weights = self._current_weights()
        try:
            rows = self.dataset.rows(period)
        except Exception as exc:  # noqa: BLE001 - dashboard should degrade cleanly on fresh deployments
            return OptimizerReport(
                status="empty",
                can_apply=False,
                sample_count=0,
                min_recommended_sample=self.min_recommended_sample,
                wins=0,
                losses=0,
                hit_rate=0.0,
                roi=0.0,
                confidence_error=0.0,
                current_weights=current_weights,
                suggested_weights=current_weights,
                warnings=["模型优化暂不可用：数据库尚未准备好或暂无已结算预测样本。"],
            )
        actionable = [row for row in rows if row.get("actionable", True)]
        scored = actionable or rows
        wins = sum(1 for row in scored if row.get("won"))
        losses = max(0, len(scored) - wins)
        metrics = calculate_metrics(rows)
        warnings = self._warnings(len(rows), metrics.confidence_calibration_error)

        if not rows:
            return OptimizerReport(
                status="empty",
                can_apply=False,
                sample_count=0,
                min_recommended_sample=self.min_recommended_sample,
                wins=0,
                losses=0,
                hit_rate=0.0,
                roi=0.0,
                confidence_error=0.0,
                current_weights=current_weights,
                suggested_weights=current_weights,
                warnings=warnings,
            )

        deltas = self._raw_deltas(scored)
        suggested_weights = self._apply_deltas(current_weights, deltas)
        suggestions = self._suggestions(current_weights, suggested_weights, rows)
        status = "stable" if not suggestions else ("ready" if len(rows) >= self.min_recommended_sample else "observe")
        return OptimizerReport(
            status=status,
            can_apply=bool(suggestions),
            sample_count=len(rows),
            min_recommended_sample=self.min_recommended_sample,
            wins=wins,
            losses=losses,
            hit_rate=metrics.signal_hit_rate,
            roi=metrics.roi,
            confidence_error=metrics.confidence_calibration_error,
            current_weights=current_weights,
            suggested_weights=suggested_weights,
            suggestions=suggestions,
            warnings=warnings,
        )

    def apply(self, period: str = "monthly") -> dict:
        report = self.build_report(period)
        if not report.can_apply:
            return {
                "success": False,
                "applied": False,
                "message": "当前没有可应用的权重建议。",
                "report": report.to_dict(),
            }
        version = f"v1-opt-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        with self.session_factory() as session:
            repo = SportsRepository(session)
            model_version = repo.get_or_create_model_version(
                name="Hunter",
                version=version,
                weight_config=report.suggested_weights,
            )
            model_version.is_active = True
            session.commit()
        return {
            "success": True,
            "applied": True,
            "message": "模型权重建议已手动应用。",
            "version": version,
            "report": report.to_dict(),
        }

    def _current_weights(self) -> dict[str, float]:
        try:
            with self.session_factory() as session:
                return load_active_rating_weights(session)
        except Exception:  # noqa: BLE001 - optimizer should always return a report
            return RATING_WEIGHTS.copy()

    def _warnings(self, sample_count: int, confidence_error: float) -> list[str]:
        warnings: list[str] = []
        if sample_count < self.min_recommended_sample:
            warnings.append(
                f"当前已结算样本 {sample_count} 场，低于建议样本 {self.min_recommended_sample} 场，调权只能作为保守试验。"
            )
        if confidence_error >= 0.15:
            warnings.append("信心校准误差偏高，建议优先观察高信心推荐是否过度乐观。")
        return warnings

    def _raw_deltas(self, rows: list[dict]) -> dict[str, float]:
        deltas = {module: 0.0 for module in RATING_WEIGHTS}
        losses = [row for row in rows if row.get("actionable", True) and not row.get("won")]
        if not losses:
            return deltas

        for row in losses:
            module = str(row.get("primary_error_module") or "unknown")
            impacts = ERROR_IMPACTS.get(module)
            if impacts is None and module in RATING_WEIGHTS:
                impacts = {module: -0.4}
            for target, impact in (impacts or {}).items():
                deltas[target] += impact

        for module, value in list(deltas.items()):
            deltas[module] = max(-MAX_DELTA_PER_MODULE, min(MAX_DELTA_PER_MODULE, value))

        total_reduction = abs(sum(value for value in deltas.values() if value < 0))
        receivers = [module for module in REDISTRIBUTION_TARGETS if deltas.get(module, 0) >= 0]
        receivers = receivers or list(RATING_WEIGHTS)
        addition = total_reduction / len(receivers) if receivers else 0.0
        for module in receivers:
            deltas[module] += addition
        return deltas

    def _apply_deltas(self, current_weights: dict[str, float], deltas: dict[str, float]) -> dict[str, float]:
        adjusted = {}
        for module, current in current_weights.items():
            adjusted[module] = max(MIN_WEIGHT, round(float(current) + float(deltas.get(module, 0.0)), 2))
        return _normalize_to_default_total(adjusted)

    def _suggestions(
        self,
        current_weights: dict[str, float],
        suggested_weights: dict[str, float],
        rows: list[dict],
    ) -> list[WeightAdjustmentSuggestion]:
        loss_counts = _loss_module_counts(rows)
        suggestions: list[WeightAdjustmentSuggestion] = []
        for module, current in current_weights.items():
            suggested = suggested_weights[module]
            delta = round(suggested - current, 2)
            if abs(delta) < 0.05:
                continue
            direction = "increase" if delta > 0 else "decrease"
            impacted_by = _module_evidence(module, loss_counts)
            suggestions.append(
                WeightAdjustmentSuggestion(
                    module=module,
                    label=MODULE_LABELS.get(module, module),
                    current_weight=round(current, 2),
                    suggested_weight=round(suggested, 2),
                    delta=delta,
                    direction=direction,
                    reason=_reason(direction, module),
                    evidence=impacted_by,
                    risk="样本偏少时只建议小幅试验，后续需继续复盘确认。",
                )
            )
        return sorted(suggestions, key=lambda item: (item.direction != "decrease", -abs(item.delta), item.module))


def _loss_module_counts(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        if row.get("actionable", True) and not row.get("won"):
            module = str(row.get("primary_error_module") or "unknown")
            counts[module] = counts.get(module, 0) + 1
    return counts


def _module_evidence(module: str, loss_counts: dict[str, int]) -> str:
    related = []
    if loss_counts.get(module):
        related.append(f"{MODULE_LABELS.get(module, module)}偏差 {loss_counts[module]} 场")
    for error_module, impacts in ERROR_IMPACTS.items():
        if module in impacts and loss_counts.get(error_module):
            related.append(f"{_error_label(error_module)} {loss_counts[error_module]} 场")
    return "；".join(related) if related else "来自未命中样本的保守再分配。"


def _reason(direction: str, module: str) -> str:
    label = MODULE_LABELS.get(module, module)
    if direction == "decrease":
        return f"{label}近期与未命中偏差相关，建议小幅降权。"
    return f"{label}用于承接被削减权重，增强更稳定的基础判断。"


def _error_label(module: str) -> str:
    return {
        "score_projection": "比分预测偏差",
        "totals_market": "大小球盘口偏差",
        "handicap_market": "让球盘口偏差",
        "signal": "最终信号偏差",
        "unknown": "未知偏差",
    }.get(module, module)


def _normalize_to_default_total(weights: dict[str, float]) -> dict[str, float]:
    target = round(sum(RATING_WEIGHTS.values()), 2)
    total = sum(weights.values()) or target
    normalized = {module: round(value * target / total, 2) for module, value in weights.items()}
    drift = round(target - sum(normalized.values()), 2)
    if drift:
        normalized["team_strength"] = round(normalized["team_strength"] + drift, 2)
    return normalized
