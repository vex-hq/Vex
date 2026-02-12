"""Add correction tracking column to executions.

Revision ID: 006
Revises: 005
Create Date: 2026-02-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "executions",
        sa.Column("corrected", sa.Boolean, server_default="false", nullable=False),
    )
    op.create_index(
        "idx_executions_corrected",
        "executions",
        ["org_id", "corrected"],
        postgresql_where=sa.text("corrected = TRUE"),
    )


def downgrade() -> None:
    op.drop_index("idx_executions_corrected", table_name="executions")
    op.drop_column("executions", "corrected")
