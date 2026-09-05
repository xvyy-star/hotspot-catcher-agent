"""add model provider prices and frozen LLM call costs

Revision ID: 20260716_0006
Revises: 20260706_0005
Create Date: 2026-07-16
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260716_0006"
down_revision = "20260706_0005"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return False
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    if _has_table("ai_model_provider"):
        if not _has_column("ai_model_provider", "input_cost_per_million"):
            op.add_column(
                "ai_model_provider",
                sa.Column(
                    "input_cost_per_million",
                    sa.Numeric(precision=18, scale=8),
                    server_default="0",
                    nullable=False,
                    comment="USD per 1M input tokens",
                ),
            )
        if not _has_column("ai_model_provider", "output_cost_per_million"):
            op.add_column(
                "ai_model_provider",
                sa.Column(
                    "output_cost_per_million",
                    sa.Numeric(precision=18, scale=8),
                    server_default="0",
                    nullable=False,
                    comment="USD per 1M output tokens",
                ),
            )

    if _has_table("llm_call_log") and not _has_column("llm_call_log", "estimated_cost"):
        op.add_column(
            "llm_call_log",
            sa.Column(
                "estimated_cost",
                sa.Numeric(precision=20, scale=10),
                server_default="0",
                nullable=False,
                comment="Frozen estimated call cost in USD",
            ),
        )


def downgrade() -> None:
    if _has_column("llm_call_log", "estimated_cost"):
        op.drop_column("llm_call_log", "estimated_cost")
    if _has_column("ai_model_provider", "output_cost_per_million"):
        op.drop_column("ai_model_provider", "output_cost_per_million")
    if _has_column("ai_model_provider", "input_cost_per_million"):
        op.drop_column("ai_model_provider", "input_cost_per_million")
