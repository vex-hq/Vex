"""Add guardrails table for custom rule definitions.

Stores per-agent and org-wide guardrail rules that are evaluated during
verification. Rules can be regex patterns, keyword blocklists, metric
thresholds, or LLM-evaluated natural language constraints.

Revision ID: 011
Revises: 010
Create Date: 2026-02-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guardrails",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("agent_id", sa.String(128), nullable=True),  # NULL = org-wide
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "rule_type",
            sa.String(50),
            nullable=False,
            comment="regex, keyword, threshold, or llm",
        ),
        sa.Column("condition", sa.JSON(), nullable=False),
        sa.Column(
            "action",
            sa.String(20),
            nullable=False,
            server_default="flag",
            comment="flag or block",
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Index for loading guardrails per org + agent
    op.create_index(
        "ix_guardrails_org_agent",
        "guardrails",
        ["org_id", "agent_id"],
    )

    # Index for org-wide guardrails (agent_id IS NULL)
    op.create_index(
        "ix_guardrails_org_wide",
        "guardrails",
        ["org_id"],
        postgresql_where=sa.text("agent_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("guardrails")
