"""Phase 2: add webhook delivery columns to alerts, make check_results.score nullable.

The alerts table gains columns for tracking webhook delivery attempts and
responses.  check_results.score is changed to nullable so that LLM timeout
or unable-to-verify cases can be recorded with score = NULL.

Revision ID: 005
Revises: 004
Create Date: 2026-02-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # alerts: add webhook delivery tracking columns
    op.add_column(
        "alerts",
        sa.Column("webhook_url", sa.Text, nullable=True),
    )
    op.add_column(
        "alerts",
        sa.Column(
            "delivery_attempts",
            sa.Integer,
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "alerts",
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "alerts",
        sa.Column("response_status", sa.Integer, nullable=True),
    )

    # check_results: make score nullable for timeout / unable-to-verify cases
    op.alter_column("check_results", "score", nullable=True)


def downgrade() -> None:
    # Restore check_results.score to NOT NULL (backfill NULLs first)
    op.execute("UPDATE check_results SET score = 0.0 WHERE score IS NULL")
    op.alter_column("check_results", "score", nullable=False)

    # Remove webhook delivery columns from alerts
    op.drop_column("alerts", "response_status")
    op.drop_column("alerts", "last_attempt_at")
    op.drop_column("alerts", "delivery_attempts")
    op.drop_column("alerts", "webhook_url")
