"""add system log table

Revision ID: 20260705_0003
Revises: 20260705_0002
Create Date: 2026-07-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260705_0003"
down_revision = "20260705_0002"
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
    if not _has_table("system_log"):
        op.create_table(
            "system_log",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("level", sa.String(length=20), nullable=False),
            sa.Column("module", sa.String(length=80), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("trace_id", sa.String(length=80), nullable=True),
            sa.Column("run_id", sa.String(length=80), nullable=True),
            sa.Column("extra_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    for table_name, index_name, columns in [
        ("system_log", "ix_system_log_level", ["level"]),
        ("system_log", "ix_system_log_module", ["module"]),
        ("system_log", "ix_system_log_trace_id", ["trace_id"]),
        ("system_log", "ix_system_log_run_id", ["run_id"]),
        ("system_log", "ix_system_log_created_at", ["created_at"]),
        ("hotspot_event", "ix_hotspot_event_updated_at", ["updated_at"]),
        ("hotspot_event", "ix_hotspot_event_heat_score", ["heat_score"]),
        ("agent_run", "ix_agent_run_started_at", ["started_at"]),
        ("push_delivery_log", "ix_push_delivery_log_created_at", ["created_at"]),
    ]:
        if not _has_index(table_name, index_name):
            op.create_index(index_name, table_name, columns)


def downgrade() -> None:
    if _has_table("system_log"):
        op.drop_table("system_log")
