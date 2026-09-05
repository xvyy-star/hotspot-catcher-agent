"""align schema indexes with ORM metadata

Revision ID: 20260716_0007
Revises: 20260716_0006
Create Date: 2026-07-16
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260716_0007"
down_revision = "20260716_0006"
branch_labels = None
depends_on = None


INDEXES = (
    ("ai_model_provider", "ix_ai_model_provider_created_at", ["created_at"]),
    ("hotspot_event", "ix_hotspot_event_is_fallback_sample", ["is_fallback_sample"]),
    ("hotspot_source", "ix_hotspot_source_created_at", ["created_at"]),
)


def _has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return False
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    for table_name, index_name, columns in INDEXES:
        if _has_table(table_name) and not _has_index(table_name, index_name):
            op.create_index(index_name, table_name, columns)


def downgrade() -> None:
    for table_name, index_name, _columns in reversed(INDEXES):
        if _has_index(table_name, index_name):
            op.drop_index(index_name, table_name=table_name)
