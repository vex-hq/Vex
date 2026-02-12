"""Add GIN index on organizations.api_keys for key hash lookups.

Enables efficient JSONB containment queries (@>) used by the
KeyValidator to find which org owns a given API key hash.

Revision ID: 007
Revises: 006
Create Date: 2026-02-12
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_organizations_api_keys",
        "organizations",
        ["api_keys"],
        postgresql_using="gin",
        postgresql_ops={"api_keys": "jsonb_path_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_organizations_api_keys", table_name="organizations")
