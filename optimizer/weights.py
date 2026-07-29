from __future__ import annotations

import logging
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.rating.weights import RATING_WEIGHTS
from database import models as orm
from database.session import SessionLocal

logger = logging.getLogger(__name__)


def load_active_rating_weights(session: Session | None = None, model_name: str = "Hunter") -> dict[str, float]:
    if session is not None:
        return _load_from_session(session, model_name)
    try:
        with SessionLocal() as local_session:
            return _load_from_session(local_session, model_name)
    except SQLAlchemyError as exc:
        logger.warning("active rating weights unavailable, using defaults: %s", exc)
        return RATING_WEIGHTS.copy()


def load_active_model_version(session: Session | None = None, model_name: str = "Hunter") -> str:
    if session is not None:
        return _load_version_from_session(session, model_name)
    try:
        with SessionLocal() as local_session:
            return _load_version_from_session(local_session, model_name)
    except SQLAlchemyError as exc:
        logger.warning("active model version unavailable, using v1: %s", exc)
        return "v1"


def _load_from_session(session: Session, model_name: str) -> dict[str, float]:
    try:
        model = session.scalar(
            select(orm.ModelVersion).where(
                orm.ModelVersion.name == model_name,
                orm.ModelVersion.is_active.is_(True),
            )
        )
    except SQLAlchemyError as exc:
        logger.warning("active model lookup failed, using defaults: %s", exc)
        return RATING_WEIGHTS.copy()
    if model is None or not isinstance(model.weight_config, Mapping):
        return RATING_WEIGHTS.copy()
    return _validated_weights(model.weight_config)


def _load_version_from_session(session: Session, model_name: str) -> str:
    try:
        model = session.scalar(
            select(orm.ModelVersion).where(
                orm.ModelVersion.name == model_name,
                orm.ModelVersion.is_active.is_(True),
            )
        )
    except SQLAlchemyError:
        return "v1"
    if model is None:
        return "v1"
    return model.version or "v1"


def _validated_weights(values: Mapping[str, object]) -> dict[str, float]:
    weights = RATING_WEIGHTS.copy()
    for key in RATING_WEIGHTS:
        try:
            weights[key] = float(values[key])
        except (KeyError, TypeError, ValueError):
            weights[key] = RATING_WEIGHTS[key]
    return _normalize(weights)


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    target = round(sum(RATING_WEIGHTS.values()), 2)
    total = sum(weights.values()) or target
    normalized = {key: round(value * target / total, 2) for key, value in weights.items()}
    drift = round(target - sum(normalized.values()), 2)
    if drift:
        normalized["team_strength"] = round(normalized["team_strength"] + drift, 2)
    return normalized
