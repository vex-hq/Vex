"""Add session-level tracing columns to executions table.

Adds session_id, parent_execution_id, and sequence_number for linking
multi-turn conversations and hierarchical execution trees.

Revision ID: 004
Revises: 003
Create Date: 2026-02-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "executions",
        sa.Column("session_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "executions",
        sa.Column("parent_execution_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "executions",
        sa.Column("sequence_number", sa.Integer, nullable=True),
    )

    op.create_index(
        "ix_executions_session_id_timestamp",
        "executions",
        ["session_id", "timestamp"],
    )
    op.create_index(
        "ix_executions_parent_execution_id",
        "executions",
        ["parent_execution_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_executions_parent_execution_id", "executions")
    op.drop_index("ix_executions_session_id_timestamp", "executions")
    op.drop_column("executions", "sequence_number")
    op.drop_column("executions", "parent_execution_id")
    op.drop_column("executions", "session_id")
