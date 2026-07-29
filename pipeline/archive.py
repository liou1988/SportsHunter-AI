from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from database import models as orm
from database.repositories import SportsRepository
from database.session import SessionLocal
from optimizer.weights import load_active_model_version, load_active_rating_weights
from pipeline.models import PredictionResult

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]


@dataclass(slots=True)
class ArchiveSaveResult:
    fixture_id: str
    prediction_id: int | None = None
    created: bool = False
    skipped: bool = False
    reason: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "prediction_id": self.prediction_id,
            "created": self.created,
            "skipped": self.skipped,
            "reason": self.reason,
            "error": self.error,
        }


@dataclass(slots=True)
class ArchiveBatchResult:
    items: list[ArchiveSaveResult] = field(default_factory=list)

    @property
    def created_count(self) -> int:
        return sum(1 for item in self.items if item.created)

    @property
    def reused_count(self) -> int:
        return sum(1 for item in self.items if item.skipped and item.prediction_id is not None)

    @property
    def failed_count(self) -> int:
        return sum(1 for item in self.items if item.error)

    def prediction_ids_by_fixture(self) -> dict[str, int]:
        return {
            item.fixture_id: int(item.prediction_id)
            for item in self.items
            if item.prediction_id is not None
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_count": self.created_count,
            "reused_count": self.reused_count,
            "failed_count": self.failed_count,
            "items": [item.to_dict() for item in self.items],
        }


class PredictionArchive:
    def __init__(
        self,
        session_factory: SessionFactory = SessionLocal,
        model_name: str = "Hunter",
        model_version: str = "v1",
    ) -> None:
        self.session_factory = session_factory
        self.model_name = model_name
        self.model_version = model_version

    def save(self, result: PredictionResult) -> int:
        with self.session_factory() as session:
            repo = SportsRepository(session)
            fixture = repo.upsert_fixture(result.fixture)
            active_weights = load_active_rating_weights(session, self.model_name)
            active_version = load_active_model_version(session, self.model_name)
            model_version = repo.get_or_create_model_version(
                name=self.model_name,
                version=active_version or self.model_version,
                weight_config=active_weights,
            )
            session.flush()
            prediction = self._create_prediction(repo, fixture, model_version, result)
            session.commit()
            return int(prediction.id)

    def save_if_changed(self, result: PredictionResult) -> ArchiveSaveResult:
        """Archive a prediction snapshot unless the latest DB snapshot is identical."""
        fixture_id = getattr(getattr(result, "fixture", None), "id", "unknown")
        try:
            with self.session_factory() as session:
                repo = SportsRepository(session)
                fixture = repo.upsert_fixture(result.fixture)
                active_weights = load_active_rating_weights(session, self.model_name)
                active_version = load_active_model_version(session, self.model_name)
                model_version = repo.get_or_create_model_version(
                    name=self.model_name,
                    version=active_version or self.model_version,
                    weight_config=active_weights,
                )
                session.flush()

                signature = _result_signature(result)
                latest = session.scalar(
                    select(orm.Prediction)
                    .where(
                        orm.Prediction.fixture_id == fixture.id,
                        orm.Prediction.model_version_id == model_version.id,
                    )
                    .order_by(desc(orm.Prediction.created_at), desc(orm.Prediction.id))
                    .limit(1)
                )
                if latest is not None and _prediction_signature(latest) == signature:
                    return ArchiveSaveResult(
                        fixture_id=str(result.fixture.id),
                        prediction_id=int(latest.id),
                        created=False,
                        skipped=True,
                        reason="unchanged",
                    )

                prediction = self._create_prediction(
                    repo,
                    fixture,
                    model_version,
                    result,
                    archive_signature=signature,
                )
                session.commit()
                return ArchiveSaveResult(
                    fixture_id=str(result.fixture.id),
                    prediction_id=int(prediction.id),
                    created=True,
                    skipped=False,
                    reason="created",
                )
        except Exception as exc:  # noqa: BLE001 - callers should keep serving recommendations
            logger.exception("prediction archive snapshot failed", extra={"fixture_id": fixture_id}, exc_info=exc)
            return ArchiveSaveResult(fixture_id=str(fixture_id), skipped=True, reason="failed", error=str(exc))

    def save_many(self, results: list[PredictionResult]) -> list[int]:
        prediction_ids: list[int] = []
        for result in results:
            try:
                prediction_ids.append(self.save(result))
            except Exception as exc:  # noqa: BLE001 - archival failure should not break prediction delivery
                logger.exception("prediction archive failed", extra={"fixture_id": result.fixture.id}, exc_info=exc)
        return prediction_ids

    def save_many_if_changed(self, results: list[PredictionResult]) -> ArchiveBatchResult:
        return ArchiveBatchResult(items=[self.save_if_changed(result) for result in results])

    def _create_prediction(
        self,
        repo: SportsRepository,
        fixture: orm.Fixture,
        model_version: orm.ModelVersion,
        result: PredictionResult,
        archive_signature: dict[str, Any] | None = None,
    ) -> orm.Prediction:
        breakdown_json = {
            "hunter_score": result.hunter_score.to_dict(),
            "risk": result.risk.to_dict(),
            "signal": result.signal.to_dict(),
            "market_prediction": result.market_prediction.to_dict(),
            "model": {
                "name": model_version.name,
                "version": model_version.version,
                "weights": model_version.weight_config or {},
            },
            "archived_at": datetime.now(timezone.utc).isoformat(),
        }
        if archive_signature is not None:
            breakdown_json["archive_signature"] = archive_signature
        return repo.save_prediction(
            fixture=fixture,
            predicted_side=result.predicted_side,
            hunter_score=result.hunter_score.score,
            grade=result.hunter_score.grade,
            confidence=result.hunter_score.confidence,
            risk_level=result.risk.level.value,
            risk_score=result.risk.score,
            signal=result.signal.signal.value,
            stake=result.signal.stake,
            priority=result.signal.priority,
            reason=result.signal.reason,
            feature_json=result.features.to_dict(),
            breakdown_json=breakdown_json,
            model_version=model_version,
        )


def _result_signature(result: PredictionResult) -> dict[str, Any]:
    market = result.market_prediction.to_dict()
    score = market.get("score") or {}
    totals = market.get("total_goals") or {}
    handicap = market.get("handicap") or {}
    return {
        "signal": result.signal.signal.value,
        "stake": _round(result.signal.stake, 2),
        "priority": int(result.signal.priority),
        "hunter_score": _round(result.hunter_score.score, 2),
        "confidence": _round(result.hunter_score.confidence, 3),
        "risk_level": result.risk.level.value,
        "risk_score": _round(result.risk.score, 2),
        "predicted_side": result.predicted_side,
        "score_text": score.get("text"),
        "moneyline_pick": market.get("moneyline_pick"),
        "total_pick": totals.get("pick"),
        "total_line": _round(totals.get("line"), 2),
        "total_label": totals.get("label"),
        "handicap_pick": handicap.get("pick"),
        "handicap_side": handicap.get("side"),
        "handicap_line": _round(handicap.get("line"), 2),
        "handicap_label": handicap.get("label"),
    }


def _prediction_signature(prediction: orm.Prediction) -> dict[str, Any]:
    breakdown = prediction.breakdown_json or {}
    signature = breakdown.get("archive_signature")
    if isinstance(signature, dict):
        return signature
    market = breakdown.get("market_prediction") or {}
    score = market.get("score") or {}
    totals = market.get("total_goals") or {}
    handicap = market.get("handicap") or {}
    return {
        "signal": prediction.signal,
        "stake": _round(prediction.stake, 2),
        "priority": int(prediction.priority or 0),
        "hunter_score": _round(prediction.hunter_score, 2),
        "confidence": _round(prediction.confidence, 3),
        "risk_level": prediction.risk_level,
        "risk_score": _round(prediction.risk_score, 2),
        "predicted_side": prediction.predicted_side,
        "score_text": score.get("text"),
        "moneyline_pick": market.get("moneyline_pick"),
        "total_pick": totals.get("pick"),
        "total_line": _round(totals.get("line"), 2),
        "total_label": totals.get("label"),
        "handicap_pick": handicap.get("pick"),
        "handicap_side": handicap.get("side"),
        "handicap_line": _round(handicap.get("line"), 2),
        "handicap_label": handicap.get("label"),
    }


def _round(value: Any, digits: int) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None
