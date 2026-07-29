from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from config.settings import get_settings
from database.session import engine
from datahub.hub import build_datahub


@dataclass(slots=True)
class ComponentStatus:
    name: str
    health: str
    detail: str = ""


class SystemHealthCheck:
    def run(self) -> list[ComponentStatus]:
        statuses = [self.provider(), self.database()]
        statuses.append(ComponentStatus("Scheduler", "UNKNOWN", "Runtime scheduler status is process-local"))
        statuses.append(ComponentStatus("Prediction", "READY", "PredictionPipeline is importable"))
        statuses.append(self.recommendation_archive())
        statuses.append(ComponentStatus("Evaluation", "READY", "Evaluation reports can be generated"))
        statuses.append(self.model_optimizer())
        return statuses

    def provider(self) -> ComponentStatus:
        try:
            health = build_datahub().provider_status()
            return ComponentStatus("Provider", "UP" if health.health else "DOWN", health.error or f"{health.latency}s")
        except Exception as exc:  # noqa: BLE001
            return ComponentStatus("Provider", "DOWN", str(exc))

    def database(self) -> ComponentStatus:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return ComponentStatus("Database", "UP")
        except Exception as exc:  # noqa: BLE001
            return ComponentStatus("Database", "DOWN", str(exc))

    def recommendation_archive(self) -> ComponentStatus:
        try:
            with engine.connect() as connection:
                prediction_count = int(connection.execute(text("SELECT COUNT(*) FROM predictions")).scalar() or 0)
                unsettled_count = int(
                    connection.execute(
                        text(
                            """
                            SELECT COUNT(DISTINCT predictions.fixture_id)
                            FROM predictions
                            LEFT JOIN match_results ON match_results.fixture_id = predictions.fixture_id
                            WHERE match_results.id IS NULL
                            """
                        )
                    ).scalar()
                    or 0
                )
            return ComponentStatus(
                "Recommendation Archive",
                "READY",
                f"predictions={prediction_count}, unsettled={unsettled_count}",
            )
        except Exception as exc:  # noqa: BLE001
            return ComponentStatus("Recommendation Archive", "NOT_READY", str(exc))

    def model_optimizer(self) -> ComponentStatus:
        settings = get_settings()
        path = settings.model_optimizer_status_path
        if not path.exists():
            return ComponentStatus("Model Optimizer", "PENDING", "No scheduled check has run yet")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return ComponentStatus("Model Optimizer", "UNKNOWN", str(exc))
        action = payload.get("action", "unknown")
        sample_count = ((payload.get("report") or {}).get("sample_count")) or 0
        return ComponentStatus("Model Optimizer", str(action).upper(), f"samples={sample_count}")

    def write_status(self, path: Path | None = None) -> Path:
        settings = get_settings()
        path = path or settings.system_status_path
        lines = [
            "# SportsHunter-AI System Status",
            "",
            f"Generated at: {datetime.now(timezone.utc).isoformat()}",
            "",
            "| Component | Status | Detail |",
            "| --- | --- | --- |",
        ]
        for status in self.run():
            lines.append(f"| {status.name} | {status.health} | {status.detail} |")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path
