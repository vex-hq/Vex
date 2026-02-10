"""Initial AgentGuard schema.

Creates all core tables (organizations, agents, executions, check_results,
alerts, human_reviews), converts time-series tables to TimescaleDB hypertables,
adds indexes, and sets up the agent_health_hourly continuous aggregate.

Revision ID: 001
Revises: None
Create Date: 2026-02-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. organizations
    # ------------------------------------------------------------------
    op.create_table(
        "organizations",
        sa.Column("org_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("api_keys", JSONB, server_default="[]", nullable=False),
        sa.Column("plan", sa.String(50), server_default="free", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # ------------------------------------------------------------------
    # 2. agents
    # ------------------------------------------------------------------
    op.create_table(
        "agents",
        sa.Column("agent_id", sa.String(128), primary_key=True),
        sa.Column(
            "org_id",
            sa.String(64),
            sa.ForeignKey("organizations.org_id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("task", sa.Text, nullable=True),
        sa.Column("config", JSONB, server_default="{}", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_agents_org_id", "agents", ["org_id"])

    # ------------------------------------------------------------------
    # 3. executions  (TimescaleDB hypertable)
    # ------------------------------------------------------------------
    op.create_table(
        "executions",
        sa.Column("execution_id", sa.String(64), nullable=False),
        sa.Column("agent_id", sa.String(128), nullable=False),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column(
            "action", sa.String(10), server_default="pass", nullable=False
        ),
        sa.Column("latency_ms", sa.Float, nullable=True),
        sa.Column("token_count", sa.Integer, nullable=True),
        sa.Column("cost_estimate", sa.Float, nullable=True),
        sa.Column("correction_layers_used", JSONB, nullable=True),
        sa.Column("trace_payload_ref", sa.Text, nullable=True),
        sa.Column(
            "status", sa.String(20), server_default="pass", nullable=False
        ),
        sa.Column("task", sa.Text, nullable=True),
        sa.Column("metadata", JSONB, server_default="{}", nullable=False),
        # Composite PK required by TimescaleDB — the partitioning column
        # (timestamp) must be part of any unique constraint.
        sa.PrimaryKeyConstraint("execution_id", "timestamp"),
    )

    # Convert to TimescaleDB hypertable
    op.execute(
        "SELECT create_hypertable('executions', 'timestamp', "
        "migrate_data => true)"
    )

    op.create_index(
        "ix_executions_agent_id_timestamp",
        "executions",
        ["agent_id", "timestamp"],
    )
    op.create_index(
        "ix_executions_org_id_timestamp",
        "executions",
        ["org_id", "timestamp"],
    )

    # ------------------------------------------------------------------
    # 4. check_results  (TimescaleDB hypertable)
    # ------------------------------------------------------------------
    op.create_table(
        "check_results",
        sa.Column(
            "id",
            sa.BigInteger,
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("execution_id", sa.String(64), nullable=False),
        sa.Column("check_type", sa.String(50), nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("details", JSONB, server_default="{}", nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Composite PK required by TimescaleDB
        sa.PrimaryKeyConstraint("id", "timestamp"),
    )

    # Convert to TimescaleDB hypertable
    op.execute(
        "SELECT create_hypertable('check_results', 'timestamp', "
        "migrate_data => true)"
    )

    op.create_index(
        "ix_check_results_execution_id",
        "check_results",
        ["execution_id"],
    )

    # ------------------------------------------------------------------
    # 5. alerts
    # ------------------------------------------------------------------
    op.create_table(
        "alerts",
        sa.Column("alert_id", sa.String(64), primary_key=True),
        sa.Column("execution_id", sa.String(64), nullable=False),
        sa.Column("agent_id", sa.String(128), nullable=False),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("alert_type", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column(
            "delivered", sa.Boolean, server_default="false", nullable=False
        ),
        sa.Column("webhook_response", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_alerts_agent_id", "alerts", ["agent_id"])
    op.create_index("ix_alerts_org_id", "alerts", ["org_id"])

    # ------------------------------------------------------------------
    # 6. human_reviews  (v2 — created now for schema stability)
    # ------------------------------------------------------------------
    op.create_table(
        "human_reviews",
        sa.Column(
            "id", sa.BigInteger, autoincrement=True, primary_key=True
        ),
        sa.Column("execution_id", sa.String(64), nullable=False),
        sa.Column("reviewer", sa.String(255), nullable=False),
        sa.Column("verdict", sa.String(50), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # ------------------------------------------------------------------
    # Continuous Aggregate: agent_health_hourly
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE MATERIALIZED VIEW agent_health_hourly
        WITH (timescaledb.continuous) AS
        SELECT
            agent_id,
            time_bucket('1 hour', timestamp) AS bucket,
            COUNT(*) AS execution_count,
            AVG(confidence) AS avg_confidence,
            COUNT(*) FILTER (WHERE action = 'pass') AS pass_count,
            COUNT(*) FILTER (WHERE action = 'flag') AS flag_count,
            COUNT(*) FILTER (WHERE action = 'block') AS block_count,
            SUM(token_count) AS total_tokens,
            SUM(cost_estimate) AS total_cost,
            AVG(latency_ms) AS avg_latency
        FROM executions
        GROUP BY agent_id, bucket
        WITH NO DATA;
        """
    )

    # Refresh policy: refresh every 1 minute, covering the last 2 hours
    op.execute(
        """
        SELECT add_continuous_aggregate_policy('agent_health_hourly',
            start_offset    => INTERVAL '3 hours',
            end_offset      => INTERVAL '1 hour',
            schedule_interval => INTERVAL '1 hour'
        );
        """
    )


def downgrade() -> None:
    # Drop in reverse dependency order.

    # 1. Remove the continuous aggregate refresh policy and view first
    op.execute(
        "SELECT remove_continuous_aggregate_policy('agent_health_hourly', "
        "if_exists => true)"
    )
    op.execute("DROP MATERIALIZED VIEW IF EXISTS agent_health_hourly CASCADE")

    # 2. Drop tables in reverse creation order
    op.drop_table("human_reviews")
    op.drop_table("alerts")
    op.drop_table("check_results")
    op.drop_table("executions")
    op.drop_table("agents")
    op.drop_table("organizations")
