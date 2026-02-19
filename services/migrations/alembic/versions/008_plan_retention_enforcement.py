"""Add plan-based data retention enforcement.

Creates a PL/pgSQL function that deletes execution and check_result
data older than each organisation's plan allows:

  free  →  7 days
  pro   → 30 days
  team  → 90 days

Designed to be called periodically by pg_cron or an external scheduler.

Revision ID: 008
Revises: 007
Create Date: 2026-02-19
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION enforce_plan_retention()
        RETURNS void AS $$
        DECLARE
            org RECORD;
            retention_days INT;
        BEGIN
            FOR org IN SELECT org_id, plan FROM organizations LOOP
                retention_days := CASE org.plan
                    WHEN 'team' THEN 90
                    WHEN 'pro' THEN 30
                    ELSE 7
                END;

                DELETE FROM check_results cr
                USING executions e
                WHERE cr.execution_id = e.execution_id
                  AND e.org_id = org.org_id
                  AND cr.timestamp < NOW() - (retention_days || ' days')::INTERVAL;

                DELETE FROM executions
                WHERE org_id = org.org_id
                  AND timestamp < NOW() - (retention_days || ' days')::INTERVAL;
            END LOOP;
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS enforce_plan_retention();")
