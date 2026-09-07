"""Persist accounts and session revocation versions.

Revision ID: 20260905_0008
Revises: 20260716_0007
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260905_0008"
down_revision = "20260716_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "app_user" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "app_user",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="user"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("auth_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_app_user_username", "app_user", ["username"], unique=True)


def downgrade() -> None:
    op.drop_table("app_user")
