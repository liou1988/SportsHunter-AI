"""beta v1 schema

Revision ID: 202607260001
Revises:
Create Date: 2026-07-26
"""

from alembic import op
import sqlalchemy as sa

revision = "202607260001"
down_revision = None
branch_labels = None
depends_on = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    ]


def upgrade() -> None:
    op.create_table(
        "leagues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("provider_league_id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("country", sa.String(128)),
        sa.Column("sport", sa.String(64), nullable=False, server_default="football"),
        *timestamps(),
        sa.UniqueConstraint("provider", "provider_league_id", name="uq_leagues_provider"),
    )
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("provider_team_id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("abbreviation", sa.String(64)),
        sa.Column("country", sa.String(128)),
        *timestamps(),
        sa.UniqueConstraint("provider", "provider_team_id", name="uq_teams_provider"),
    )
    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("weight_config", sa.JSON()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        *timestamps(),
    )
    op.create_table(
        "fixtures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("provider_fixture_id", sa.String(128), nullable=False),
        sa.Column("sport", sa.String(64), nullable=False, server_default="football"),
        sa.Column("league_id", sa.Integer(), sa.ForeignKey("leagues.id"), nullable=False),
        sa.Column("home_team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("away_team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("venue", sa.String(255)),
        sa.Column("season", sa.Integer()),
        sa.Column("round_name", sa.String(255)),
        sa.Column("raw", sa.JSON()),
        *timestamps(),
        sa.UniqueConstraint("provider", "provider_fixture_id", name="uq_fixtures_provider"),
    )
    op.create_table(
        "odds_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fixture_id", sa.Integer(), sa.ForeignKey("fixtures.id"), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("bookmaker", sa.String(128), nullable=False),
        sa.Column("market", sa.String(64), nullable=False),
        sa.Column("line", sa.Float()),
        sa.Column("home", sa.Float()),
        sa.Column("draw", sa.Float()),
        sa.Column("away", sa.Float()),
        sa.Column("over", sa.Float()),
        sa.Column("under", sa.Float()),
        sa.Column("stage", sa.String(32), nullable=False, server_default="pre_match"),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw", sa.JSON()),
        *timestamps(),
    )
    op.create_table(
        "match_statistics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fixture_id", sa.Integer(), sa.ForeignKey("fixtures.id"), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False, server_default="pre_match"),
        sa.Column("home_possession", sa.Float()),
        sa.Column("away_possession", sa.Float()),
        sa.Column("home_shots", sa.Integer()),
        sa.Column("away_shots", sa.Integer()),
        sa.Column("home_shots_on_target", sa.Integer()),
        sa.Column("away_shots_on_target", sa.Integer()),
        sa.Column("home_corners", sa.Integer()),
        sa.Column("away_corners", sa.Integer()),
        sa.Column("home_red_cards", sa.Integer()),
        sa.Column("away_red_cards", sa.Integer()),
        sa.Column("raw", sa.JSON()),
        *timestamps(),
    )
    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fixture_id", sa.Integer(), sa.ForeignKey("fixtures.id"), nullable=False),
        sa.Column("model_version_id", sa.Integer(), sa.ForeignKey("model_versions.id")),
        sa.Column("predicted_side", sa.String(64)),
        sa.Column("hunter_score", sa.Float(), nullable=False),
        sa.Column("grade", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("risk_level", sa.String(32), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("signal", sa.String(32), nullable=False),
        sa.Column("stake", sa.Float(), nullable=False, server_default="0"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason", sa.Text()),
        sa.Column("feature_json", sa.JSON()),
        sa.Column("breakdown_json", sa.JSON()),
        *timestamps(),
    )
    op.create_table(
        "match_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fixture_id", sa.Integer(), sa.ForeignKey("fixtures.id"), unique=True, nullable=False),
        sa.Column("home_score", sa.Integer()),
        sa.Column("away_score", sa.Integer()),
        sa.Column("winner", sa.String(64)),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.Column("raw", sa.JSON()),
        *timestamps(),
    )
    op.create_table(
        "learning_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("prediction_id", sa.Integer(), sa.ForeignKey("predictions.id")),
        sa.Column("fixture_id", sa.Integer(), sa.ForeignKey("fixtures.id")),
        sa.Column("outcome", sa.String(64), nullable=False),
        sa.Column("module", sa.String(128)),
        sa.Column("adjustment", sa.JSON()),
        sa.Column("notes", sa.Text()),
        *timestamps(),
    )
    op.create_table(
        "sync_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("sync_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("synced_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency", sa.Float()),
        sa.Column("error", sa.Text()),
        *timestamps(),
    )
    op.create_table(
        "collection_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("collected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        *timestamps(),
    )


def downgrade() -> None:
    for table in [
        "collection_runs",
        "sync_logs",
        "learning_records",
        "match_results",
        "predictions",
        "match_statistics",
        "odds_snapshots",
        "fixtures",
        "model_versions",
        "teams",
        "leagues",
    ]:
        op.drop_table(table)
