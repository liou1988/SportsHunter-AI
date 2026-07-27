from __future__ import annotations


class EvaluationAnalyzer:
    def explain(self, row: dict) -> str:
        if row.get("won"):
            return "命中原因：评分、风险和市场信号保持一致。"
        module = row.get("primary_error_module") or "unknown"
        return f"未命中原因：{module} 存在偏差，需要结合盘口和赛果复核。"

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
