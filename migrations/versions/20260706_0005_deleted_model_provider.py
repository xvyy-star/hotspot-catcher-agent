"""add deleted model provider tombstone table

Revision ID: 20260706_0005
Revises: 20260706_0004
Create Date: 2026-07-06
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260706_0005"
down_revision = "20260706_0004"
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
    if not _has_table("deleted_model_provider"):
        op.create_table(
            "deleted_model_provider",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("code", sa.String(length=80), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=True),
            sa.Column("deleted_by", sa.String(length=80), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("code"),
        )
    for index_name, columns in [
        ("ix_deleted_model_provider_code", ["code"]),
        ("ix_deleted_model_provider_created_at", ["created_at"]),
    ]:
        if not _has_index("deleted_model_provider", index_name):
            op.create_index(index_name, "deleted_model_provider", columns)


def downgrade() -> None:
    if _has_table("deleted_model_provider"):
        op.drop_table("deleted_model_provider")
