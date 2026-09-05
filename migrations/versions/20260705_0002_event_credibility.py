"""add event credibility fields

Revision ID: 20260705_0002
Revises: 20260705_0001
Create Date: 2026-07-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260705_0002"
down_revision = "20260705_0001"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    if not _has_column("hotspot_event", "credibility_score"):
        op.add_column("hotspot_event", sa.Column("credibility_score", sa.Float(), nullable=False, server_default="0"))
    if not _has_column("hotspot_event", "credibility_level"):
        op.add_column("hotspot_event", sa.Column("credibility_level", sa.String(length=20), nullable=True))
    if not _has_column("hotspot_event", "credibility_reason"):
        op.add_column("hotspot_event", sa.Column("credibility_reason", sa.Text(), nullable=True))
    if not _has_column("hotspot_event", "is_fallback_sample"):
        op.add_column("hotspot_event", sa.Column("is_fallback_sample", sa.Boolean(), nullable=False, server_default=sa.false()))
        op.create_index("ix_hotspot_event_is_fallback_sample", "hotspot_event", ["is_fallback_sample"])


def downgrade() -> None:
    if _has_column("hotspot_event", "is_fallback_sample"):
        op.drop_index("ix_hotspot_event_is_fallback_sample", table_name="hotspot_event")
        op.drop_column("hotspot_event", "is_fallback_sample")
    if _has_column("hotspot_event", "credibility_reason"):
        op.drop_column("hotspot_event", "credibility_reason")
    if _has_column("hotspot_event", "credibility_level"):
        op.drop_column("hotspot_event", "credibility_level")
    if _has_column("hotspot_event", "credibility_score"):
        op.drop_column("hotspot_event", "credibility_score")
