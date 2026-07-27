from __future__ import annotations


class EvaluationAnalyzer:
    def explain(self, row: dict) -> str:
        if row.get("won"):
            return "命中原因：评分、风险和市场信号保持一致。"
        module = row.get("primary_error_module") or "unknown"
        return f"未命中原因：{module} 存在偏差，需要结合盘口和赛果复核。"

    def win_notes(self, rows: list[dict], limit: int = 8) -> list[str]:
        wins = [row for row in rows if row.get("actionable", True) and row.get("won")]
        if not wins:
            return ["本周期暂无命中推荐。"]
        ordered = sorted(wins, key=lambda row: float(row.get("hunter_score") or 0), reverse=True)
        return [self._row_note(row, "命中") for row in ordered[:limit]]

    def loss_notes(self, rows: list[dict], limit: int = 8) -> list[str]:
        losses = [row for row in rows if row.get("actionable", True) and not row.get("won")]
        if not losses:
            return ["本周期暂无未命中推荐。"]
        ordered = sorted(losses, key=lambda row: float(row.get("stake") or 0), reverse=True)
        return [self._row_note(row, "未命中") for row in ordered[:limit]]

    def module_notes(self, rows: list[dict]) -> list[str]:
        if not rows:
            return ["暂无已结算预测。"]
        losses = [row for row in rows if row.get("actionable", True) and not row.get("won")]
        if not losses:
            return ["本周期可下注信号全部命中，暂不建议调整权重。"]
        modules: dict[str, int] = {}
        for row in losses:
            module = str(row.get("primary_error_module") or "unknown")
            modules[module] = modules.get(module, 0) + 1
        ordered = sorted(modules.items(), key=lambda item: item[1], reverse=True)
        return [f"优先复核 {module}：{count} 场未命中。" for module, count in ordered[:3]]

    def _row_note(self, row: dict, outcome: str) -> str:
        result = _score_text(row)
        market = _market_text(row)
        module = row.get("primary_error_module") or "unknown"
        score_error = row.get("score_error")
        confidence = _format_number(row.get("confidence"))
        hunter_score = _format_number(row.get("hunter_score"))
        if outcome == "命中":
            reason = "评分优势、风险控制和盘口判断同向。"
        else:
            reason = f"主要偏差来自 {module}，比分误差 {score_error if score_error is not None else '-'}。"
        return (
            f"{outcome}：{row.get('fixture', '-')}"
            f" | 信号 {row.get('signal', '-')}"
            f" | 赛果 {result}"
            f" | Hunter {hunter_score}"
            f" | 信心 {confidence}"
            f" | {market}"
            f" | {reason}"
        )


def _score_text(row: dict) -> str:
    home_score = row.get("home_score")
    away_score = row.get("away_score")
    if home_score is None or away_score is None:
        return "-"
    return f"{home_score}-{away_score}"


def _market_text(row: dict) -> str:
    parts = []
    market_results = row.get("market_results") or {}
    for market, label in [("moneyline", "胜平负"), ("totals", "大小球"), ("handicap", "让球")]:
        value = market_results.get(market)
        if value is None:
            parts.append(f"{label}未评估")
        else:
            parts.append(f"{label}{'命中' if value else '未中'}")
    return "，".join(parts)


def _format_number(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number:.2f}".rstrip("0").rstrip(".")
