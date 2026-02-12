"""Add account_slug column to organizations for MakerKit integration.

Maps MakerKit team-account slugs (URL segments) to AgentGuard org_ids,
enabling proper multi-tenancy in the dashboard.

Revision ID: 003
Revises: 002
Create Date: 2026-02-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("account_slug", sa.String(128), nullable=True),
    )
    op.create_index(
        "ix_organizations_account_slug",
        "organizations",
        ["account_slug"],
        unique=True,
    )
    # Backfill: set slug = org_id for existing rows so the fallback lookup works
    op.execute(
        "UPDATE organizations SET account_slug = org_id WHERE account_slug IS NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_organizations_account_slug", "organizations")
    op.drop_column("organizations", "account_slug")
