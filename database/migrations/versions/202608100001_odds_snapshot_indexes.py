"""add odds snapshot lookup index"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202608100001"
down_revision = "202607260001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing_indexes = {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes("odds_snapshots")
    }
    if "ix_odds_snapshots_fixture_id_captured_at" in existing_indexes:
        return
    op.create_index(
        "ix_odds_snapshots_fixture_id_captured_at",
        "odds_snapshots",
        ["fixture_id", "captured_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_odds_snapshots_fixture_id_captured_at", table_name="odds_snapshots")
