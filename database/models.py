from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class League(Base, TimestampMixin):
    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_league_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str | None] = mapped_column(String(128))
    sport: Mapped[str] = mapped_column(String(64), default="football", nullable=False)

    fixtures: Mapped[list["Fixture"]] = relationship(back_populates="league")

    __table_args__ = (UniqueConstraint("provider", "provider_league_id"),)


class Team(Base, TimestampMixin):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_team_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    abbreviation: Mapped[str | None] = mapped_column(String(64))
    country: Mapped[str | None] = mapped_column(String(128))

    home_fixtures: Mapped[list["Fixture"]] = relationship(
        back_populates="home_team",
        foreign_keys="Fixture.home_team_id",
    )
    away_fixtures: Mapped[list["Fixture"]] = relationship(
        back_populates="away_team",
        foreign_keys="Fixture.away_team_id",
    )

    __table_args__ = (UniqueConstraint("provider", "provider_team_id"),)


class Fixture(Base, TimestampMixin):
    __tablename__ = "fixtures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_fixture_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sport: Mapped[str] = mapped_column(String(64), default="football", nullable=False)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), nullable=False)
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    venue: Mapped[str | None] = mapped_column(String(255))
    season: Mapped[int | None] = mapped_column(Integer)
    round_name: Mapped[str | None] = mapped_column(String(255))
    raw: Mapped[dict | None] = mapped_column(JSON)

    league: Mapped[League] = relationship(back_populates="fixtures")
    home_team: Mapped[Team] = relationship(back_populates="home_fixtures", foreign_keys=[home_team_id])
    away_team: Mapped[Team] = relationship(back_populates="away_fixtures", foreign_keys=[away_team_id])
    odds_snapshots: Mapped[list["OddsSnapshot"]] = relationship(back_populates="fixture")
    statistics: Mapped[list["MatchStatistics"]] = relationship(back_populates="fixture")
    predictions: Mapped[list["Prediction"]] = relationship(back_populates="fixture")
    result: Mapped["MatchResult | None"] = relationship(back_populates="fixture")

    __table_args__ = (UniqueConstraint("provider", "provider_fixture_id"),)


class OddsSnapshot(Base, TimestampMixin):
    __tablename__ = "odds_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    bookmaker: Mapped[str] = mapped_column(String(128), nullable=False)
    market: Mapped[str] = mapped_column(String(64), nullable=False)
    line: Mapped[float | None] = mapped_column(Float)
    home: Mapped[float | None] = mapped_column(Float)
    draw: Mapped[float | None] = mapped_column(Float)
    away: Mapped[float | None] = mapped_column(Float)
    over: Mapped[float | None] = mapped_column(Float)
    under: Mapped[float | None] = mapped_column(Float)
    stage: Mapped[str] = mapped_column(String(32), default="pre_match", nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw: Mapped[dict | None] = mapped_column(JSON)

    fixture: Mapped[Fixture] = relationship(back_populates="odds_snapshots")


class MatchStatistics(Base, TimestampMixin):
    __tablename__ = "match_statistics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), default="pre_match", nullable=False)
    home_possession: Mapped[float | None] = mapped_column(Float)
    away_possession: Mapped[float | None] = mapped_column(Float)
    home_shots: Mapped[int | None] = mapped_column(Integer)
    away_shots: Mapped[int | None] = mapped_column(Integer)
    home_shots_on_target: Mapped[int | None] = mapped_column(Integer)
    away_shots_on_target: Mapped[int | None] = mapped_column(Integer)
    home_corners: Mapped[int | None] = mapped_column(Integer)
    away_corners: Mapped[int | None] = mapped_column(Integer)
    home_red_cards: Mapped[int | None] = mapped_column(Integer)
    away_red_cards: Mapped[int | None] = mapped_column(Integer)
    raw: Mapped[dict | None] = mapped_column(JSON)

    fixture: Mapped[Fixture] = relationship(back_populates="statistics")


class ModelVersion(Base, TimestampMixin):
    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    weight_config: Mapped[dict | None] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    predictions: Mapped[list["Prediction"]] = relationship(back_populates="model_version")


class Prediction(Base, TimestampMixin):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), nullable=False)
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"))
    predicted_side: Mapped[str | None] = mapped_column(String(64))
    hunter_score: Mapped[float] = mapped_column(Float, nullable=False)
    grade: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    signal: Mapped[str] = mapped_column(String(32), nullable=False)
    stake: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[str | None] = mapped_column(Text)
    feature_json: Mapped[dict | None] = mapped_column(JSON)
    breakdown_json: Mapped[dict | None] = mapped_column(JSON)

    fixture: Mapped[Fixture] = relationship(back_populates="predictions")
    model_version: Mapped[ModelVersion | None] = relationship(back_populates="predictions")


class MatchResult(Base, TimestampMixin):
    __tablename__ = "match_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), unique=True, nullable=False)
    home_score: Mapped[int | None] = mapped_column(Integer)
    away_score: Mapped[int | None] = mapped_column(Integer)
    winner: Mapped[str | None] = mapped_column(String(64))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict | None] = mapped_column(JSON)

    fixture: Mapped[Fixture] = relationship(back_populates="result")


class LearningRecord(Base, TimestampMixin):
    __tablename__ = "learning_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prediction_id: Mapped[int | None] = mapped_column(ForeignKey("predictions.id"))
    fixture_id: Mapped[int | None] = mapped_column(ForeignKey("fixtures.id"))
    outcome: Mapped[str] = mapped_column(String(64), nullable=False)
    module: Mapped[str | None] = mapped_column(String(128))
    adjustment: Mapped[dict | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)


class SyncLog(Base, TimestampMixin):
    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    sync_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)


class CollectionRun(Base, TimestampMixin):
    __tablename__ = "collection_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    collected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
