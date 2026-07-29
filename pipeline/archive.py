from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from database.repositories import SportsRepository
from database.session import SessionLocal
from optimizer.weights import load_active_model_version, load_active_rating_weights
from pipeline.models import PredictionResult

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]


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
            prediction = repo.save_prediction(
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
                breakdown_json={
                    "hunter_score": result.hunter_score.to_dict(),
                    "risk": result.risk.to_dict(),
                    "signal": result.signal.to_dict(),
                    "market_prediction": result.market_prediction.to_dict(),
                },
                model_version=model_version,
            )
            session.commit()
            return int(prediction.id)

    def save_many(self, results: list[PredictionResult]) -> list[int]:
        prediction_ids: list[int] = []
        for result in results:
            try:
                prediction_ids.append(self.save(result))
            except Exception as exc:  # noqa: BLE001 - archival failure should not break prediction delivery
                logger.exception("prediction archive failed", extra={"fixture_id": result.fixture.id}, exc_info=exc)
        return prediction_ids
