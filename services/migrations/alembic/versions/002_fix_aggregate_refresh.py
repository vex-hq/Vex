"""Fix continuous aggregate refresh policy for near-real-time dashboard data.

The original policy refreshes every 1 hour with a 1-hour end_offset, which
means data less than 1 hour old is never materialized. This makes the
"Executions Over Time" chart appear empty for recent executions.

New policy:
- schedule_interval: 1 minute (refresh frequently in dev; 5 min in prod)
- end_offset: 10 minutes (materialize data up to 10 minutes old)
- start_offset: 3 hours (unchanged — covers enough history)

Revision ID: 002
Revises: 001
Create Date: 2026-02-11
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        SELECT remove_continuous_aggregate_policy('agent_health_hourly');
        SELECT add_continuous_aggregate_policy('agent_health_hourly',
            start_offset    => INTERVAL '3 hours',
            end_offset      => INTERVAL '10 minutes',
            schedule_interval => INTERVAL '1 minute'
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        SELECT remove_continuous_aggregate_policy('agent_health_hourly');
        SELECT add_continuous_aggregate_policy('agent_health_hourly',
            start_offset    => INTERVAL '3 hours',
            end_offset      => INTERVAL '1 hour',
            schedule_interval => INTERVAL '1 hour'
        );
        """
    )
