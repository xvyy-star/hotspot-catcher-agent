"""baseline existing schema

Revision ID: 20260705_0001
Revises:
Create Date: 2026-07-05
"""
from __future__ import annotations

revision = "20260705_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 当前项目已有 Base.metadata.create_all + 轻量补列迁移。
    # 这个 baseline 用于把后续结构变更切到 Alembic 版本化管理。
    pass


def downgrade() -> None:
    pass
