from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from config.settings import Settings, get_settings
from optimizer.engine import ModelOptimizer


def run_scheduled_optimizer_check(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    if not settings.model_optimizer_enabled:
        payload = {
            "success": True,
            "enabled": False,
            "action": "disabled",
            "message": "模型优化定时检查未启用。",
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_status(settings, payload)
        return payload

    optimizer = ModelOptimizer(min_recommended_sample=settings.model_optimizer_manual_min_samples)
    report = optimizer.build_report("monthly")
    action = _action_for_report(report.to_dict(), settings)
    applied: dict[str, Any] | None = None

    if action == "auto_apply":
        applied = optimizer.apply("monthly")
        action = "auto_applied" if applied.get("applied") else "auto_apply_failed"

    payload = {
        "success": True,
        "enabled": True,
        "action": action,
        "message": _message(action),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "manual_min_samples": settings.model_optimizer_manual_min_samples,
        "auto_apply_enabled": settings.model_optimizer_auto_apply_enabled,
        "auto_apply_min_samples": settings.model_optimizer_auto_apply_min_samples,
        "applied": applied,
        "report": report.to_dict(),
    }
    _write_status(settings, payload)
    return payload


def _action_for_report(report: dict[str, Any], settings: Settings) -> str:
    sample_count = int(report.get("sample_count") or 0)
    can_apply = bool(report.get("can_apply"))
    if not can_apply:
        return "stable"
    if sample_count < settings.model_optimizer_manual_min_samples:
        return "observe"
    if settings.model_optimizer_auto_apply_enabled and sample_count >= settings.model_optimizer_auto_apply_min_samples:
        return "auto_apply"
    return "manual_review"


def _message(action: str) -> str:
    return {
        "stable": "当前权重暂不需要调整。",
        "observe": "样本不足，继续观察，不应用权重。",
        "manual_review": "样本已达手动复核阈值，请在 Dashboard 手动确认后应用。",
        "auto_applied": "样本达到自动应用阈值，已自动应用权重建议。",
        "auto_apply_failed": "尝试自动应用权重建议失败，请人工检查。",
    }.get(action, action)


def _write_status(settings: Settings, payload: dict[str, Any]) -> None:
    path = settings.model_optimizer_status_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
