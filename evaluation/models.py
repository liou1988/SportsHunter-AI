from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date


@dataclass(slots=True)
class EvaluationMetrics:
    hunter_hit_rate: float = 0.0
    signal_hit_rate: float = 0.0
    risk_effectiveness: float = 0.0
    confidence_calibration_error: float = 0.0
    roi: float = 0.0
    by_league: dict[str, float] = field(default_factory=dict)
    by_market: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class EvaluationReport:
    period: str
    report_date: date
    metrics: EvaluationMetrics
    settled_count: int = 0
    learning_records_created: int = 0
    overview: list[str] = field(default_factory=list)
    wins: list[str] = field(default_factory=list)
    losses: list[str] = field(default_factory=list)
    confidence_notes: list[str] = field(default_factory=list)
    risk_notes: list[str] = field(default_factory=list)
    module_contributions: list[str] = field(default_factory=list)
    module_notes: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            f"# SportsHunter-AI {_period_label(self.period)}复盘",
            "",
            f"- 日期：{self.report_date.isoformat()}",
            f"- 已结算预测：{self.settled_count}",
            f"- 新增学习记录：{self.learning_records_created}",
            f"- Hunter 评分命中率：{self.metrics.hunter_hit_rate:.2%}",
            f"- 信号命中率：{self.metrics.signal_hit_rate:.2%}",
            f"- 风险控制有效性：{self.metrics.risk_effectiveness:.2%}",
            f"- 信心校准误差：{self.metrics.confidence_calibration_error:.4f}",
            f"- ROI: {self.metrics.roi:.2%}",
            "",
            "## 核心结论",
            *_format_list_items(self.overview),
            "",
            "## 联赛表现",
            *_format_rate_items(self.metrics.by_league, value_map=_translate_metric_name),
            "",
            "## 盘口表现",
            *_format_rate_items(self.metrics.by_market, value_map=_translate_metric_name),
            "",
            "## 命中原因",
            *_format_list_items(self.wins),
            "",
            "## 未命中原因",
            *_format_list_items(self.losses),
            "",
            "## 信心校准",
            *_format_list_items(self.confidence_notes),
            "",
            "## 风险分层",
            *_format_list_items(self.risk_notes),
            "",
            "## 模块贡献",
            *_format_list_items(self.module_contributions),
            "",
            "## 调整建议",
            *_format_list_items(self.module_notes),
        ]
        return "\n".join(lines)


@dataclass(slots=True)
class SettlementSummary:
    checked_count: int = 0
    settled_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0

    def to_dict(self) -> dict:
        return {
            "checked_count": self.checked_count,
            "settled_count": self.settled_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
        }


def _format_rate_items(items: dict[str, float], value_map: Callable[[str], str] | None = None) -> list[str]:
    if not items:
        return ["- 暂无已结算数据。"]
    mapper = value_map or (lambda value: value)
    return [f"- {mapper(name)}：{rate:.2%}" for name, rate in sorted(items.items())]


def _format_list_items(items: list[str]) -> list[str]:
    if not items:
        return ["- 暂无数据。"]
    return [f"- {item}" for item in items]


def _period_label(period: str) -> str:
    return {
        "daily": "每日",
        "weekly": "每周",
        "monthly": "每月",
    }.get(str(period), str(period))


def _translate_metric_name(name: str) -> str:
    return {
        "moneyline": "胜平负",
        "totals": "大小球",
        "handicap": "让球",
    }.get(str(name), str(name))
