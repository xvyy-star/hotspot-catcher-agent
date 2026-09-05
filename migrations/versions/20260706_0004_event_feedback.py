"""add event feedback table

Revision ID: 20260706_0004
Revises: 20260705_0003
Create Date: 2026-07-06
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260706_0004"
down_revision = "20260705_0003"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return True
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    if not _has_table("hotspot_event_feedback"):
        op.create_table(
            "hotspot_event_feedback",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("event_key", sa.String(length=200), nullable=False),
            sa.Column("action", sa.String(length=30), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(length=80), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("event_key", "action", "created_by", name="uq_hotspot_event_feedback_once"),
        )
    for index_name, columns in [
        ("ix_hotspot_event_feedback_event_key", ["event_key"]),
        ("ix_hotspot_event_feedback_action", ["action"]),
        ("ix_hotspot_event_feedback_created_by", ["created_by"]),
        ("ix_hotspot_event_feedback_created_at", ["created_at"]),
    ]:
        if not _has_index("hotspot_event_feedback", index_name):
            op.create_index(index_name, "hotspot_event_feedback", columns)


def downgrade() -> None:
    if _has_table("hotspot_event_feedback"):
        op.drop_table("hotspot_event_feedback")
