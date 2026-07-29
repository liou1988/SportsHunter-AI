from __future__ import annotations

from telegram_bot.localization import translate_signal


class EvaluationAnalyzer:
    def explain(self, row: dict) -> str:
        if row.get("won"):
            return "命中原因：评分、风险和市场信号保持一致。"
        module = row.get("primary_error_module") or "unknown"
        return f"未命中原因：{_module_label(module)} 存在偏差，需要结合盘口和赛果复核。"

    def overview_notes(self, rows: list[dict]) -> list[str]:
        if not rows:
            return ["暂无已结算预测，等待赛果归档后生成复盘结论。"]
        actionable = [row for row in rows if row.get("actionable", True)]
        scored = actionable or rows
        wins = sum(1 for row in scored if row.get("won"))
        stake = sum(float(row.get("stake") or 0) for row in scored) or 1.0
        profit = sum(float(row.get("profit") or 0) for row in scored)
        hit_rate = wins / len(scored) if scored else 0.0
        roi = profit / stake
        notes = [
            f"本周期结算 {len(rows)} 场，其中可执行信号 {len(actionable)} 场，命中 {wins} 场，命中率 {hit_rate:.2%}，ROI {roi:.2%}。",
        ]
        best_league = _best_group(scored, "league")
        if best_league:
            notes.append(f"表现最稳定的联赛：{best_league[0]}，样本 {best_league[1]} 场，命中率 {best_league[2]:.2%}。")
        top_error = _top_error_module(scored)
        if top_error:
            notes.append(f"最需要复核的模块：{_module_label(top_error[0])}，未命中 {top_error[1]} 场。")
        return notes

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
        return [
            f"优先复核 {_module_label(module)}：{count} 场未命中，建议降低该模块单场权重或提高进入推荐的确认阈值。"
            for module, count in ordered[:3]
        ]

    def confidence_notes(self, rows: list[dict]) -> list[str]:
        actionable = [row for row in rows if row.get("actionable", True)]
        if not actionable:
            return ["暂无可执行信号，暂不评估信心校准。"]
        hit_rate = sum(1 for row in actionable if row.get("won")) / len(actionable)
        avg_confidence = _average(row.get("confidence") for row in actionable)
        gap = avg_confidence - hit_rate
        if abs(gap) <= 0.08:
            return [f"信心均值 {avg_confidence:.2f} 与实际命中率 {hit_rate:.2%} 基本匹配，当前校准可接受。"]
        if gap > 0:
            return [f"信心均值 {avg_confidence:.2f} 高于实际命中率 {hit_rate:.2%}，建议收紧高信心推荐阈值。"]
        return [f"信心均值 {avg_confidence:.2f} 低于实际命中率 {hit_rate:.2%}，可观察是否存在低估优质信号。"]

    def risk_notes(self, rows: list[dict]) -> list[str]:
        if not rows:
            return ["暂无已结算预测，暂不评估风险分层。"]
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            grouped.setdefault(str(row.get("risk_level") or "UNKNOWN"), []).append(row)
        notes = []
        for risk_level, items in sorted(grouped.items()):
            actionable = [row for row in items if row.get("actionable", True)]
            scored = actionable or items
            wins = sum(1 for row in scored if row.get("won"))
            hit_rate = wins / len(scored) if scored else 0.0
            notes.append(f"{_risk_label(risk_level)}：{len(items)} 场，命中率 {hit_rate:.2%}。")
        return notes

    def module_contribution_notes(self, rows: list[dict]) -> list[str]:
        if not rows:
            return ["暂无模块贡献数据。"]
        wins = [row for row in rows if row.get("actionable", True) and row.get("won")]
        losses = [row for row in rows if row.get("actionable", True) and not row.get("won")]
        notes = []
        if wins:
            avg_score_error = _average(row.get("score_error") for row in wins)
            notes.append(f"命中样本中，平均比分误差 {avg_score_error:.2f}，说明方向判断优先于精确比分。")
        if losses:
            top_error = _top_error_module(losses)
            if top_error:
                notes.append(f"未命中主要集中在 {_module_label(top_error[0])}，需要在后续权重迭代中优先处理。")
        market_notes = _market_module_notes(rows)
        notes.extend(market_notes)
        return notes or ["暂无明显模块偏差。"]

    def _row_note(self, row: dict, outcome: str) -> str:
        result = _score_text(row)
        predicted_score = row.get("predicted_score") or "-"
        market = _market_text(row)
        module = row.get("primary_error_module") or "unknown"
        score_error = row.get("score_error")
        confidence = _format_number(row.get("confidence"))
        hunter_score = _format_number(row.get("hunter_score"))
        if outcome == "命中":
            reason = "方向判断与赛果一致，评分优势、风险控制和盘口判断同向。"
        else:
            reason = f"主要偏差来自 {_module_label(module)}，比分误差 {score_error if score_error is not None else '-'}。"
        return (
            f"{outcome}：{row.get('fixture', '-')}"
            f" | \u4fe1\u53f7 {translate_signal(str(row.get('signal', '-')))}"
            f" | 预测 {predicted_score}"
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


def _average(values: object) -> float:
    numbers = []
    for value in values:
        try:
            if value is not None:
                numbers.append(float(value))
        except (TypeError, ValueError):
            continue
    if not numbers:
        return 0.0
    return sum(numbers) / len(numbers)


def _best_group(rows: list[dict], key: str) -> tuple[str, int, float] | None:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(key) or "unknown"), []).append(row)
    if not grouped:
        return None
    ranked = []
    for name, items in grouped.items():
        wins = sum(1 for item in items if item.get("won"))
        ranked.append((name, len(items), wins / len(items) if items else 0.0))
    return sorted(ranked, key=lambda item: (-item[2], -item[1], item[0]))[0]


def _top_error_module(rows: list[dict]) -> tuple[str, int] | None:
    losses = [row for row in rows if row.get("actionable", True) and not row.get("won")]
    if not losses:
        return None
    grouped: dict[str, int] = {}
    for row in losses:
        module = str(row.get("primary_error_module") or "unknown")
        grouped[module] = grouped.get(module, 0) + 1
    return sorted(grouped.items(), key=lambda item: (-item[1], item[0]))[0]


def _market_module_notes(rows: list[dict]) -> list[str]:
    notes = []
    for market, label in [("moneyline", "胜平负"), ("totals", "大小球"), ("handicap", "让球")]:
        hits = []
        for row in rows:
            value = (row.get("market_results") or {}).get(market)
            if value is not None:
                hits.append(bool(value))
        if not hits:
            continue
        hit_rate = sum(1 for value in hits if value) / len(hits)
        if hit_rate < 0.5:
            notes.append(f"{label}命中率 {hit_rate:.2%}，低于可接受区间，需要复核该盘口模型。")
        else:
            notes.append(f"{label}命中率 {hit_rate:.2%}，当前表现可继续观察。")
    return notes


def _module_label(module: str) -> str:
    return {
        "aligned_signal": "信号一致性",
        "score_projection": "比分预测",
        "totals_market": "大小球盘口",
        "handicap_market": "让球盘口",
        "signal": "最终信号",
        "unknown": "未知模块",
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
    }.get(str(module), str(module))


def _risk_label(risk_level: str) -> str:
    return {
        "LOW": "低风险",
        "MEDIUM": "中风险",
        "HIGH": "高风险",
        "BLOCK": "风控拦截",
        "UNKNOWN": "未知风险",
    }.get(str(risk_level), str(risk_level))
