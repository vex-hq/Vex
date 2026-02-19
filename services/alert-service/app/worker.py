"""Core processing logic for the alert service.

Receives verified events, filters for flag/block actions, resolves
webhook URLs, delivers notifications (HTTP and Slack), and records
delivery status in the alerts table.

Delivery channels are gated by the org's plan:
- ``webhook_alerts``: HTTP webhook delivery (pro+)
- ``slack_alerts``: Slack webhook delivery (team+)

This module is intentionally decoupled from the Redis consumer loop so
it can be tested in isolation.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text

from app.slack import deliver_slack, format_slack_message, get_slack_webhook_url
from app.webhook import deliver
from shared.plan_limits import get_plan_config

logger = logging.getLogger("agentguard.alert-service")

DEFAULT_ORG = "default"
DASHBOARD_BASE_URL = os.environ.get("DASHBOARD_BASE_URL")


def get_webhook_url(agent_id: str) -> Optional[str]:
    """Resolve the webhook URL for an agent.

    Checks the environment variable ``WEBHOOK_URL_{AGENT_ID}`` first
    (with hyphens replaced by underscores), then falls back to the
    default ``WEBHOOK_URL`` environment variable.

    Args:
        agent_id: The agent identifier.

    Returns:
        The webhook URL, or None if not configured.
    """
    env_key = f"WEBHOOK_URL_{agent_id.replace('-', '_').upper()}"
    url = os.environ.get(env_key)
    if url:
        return url
    return os.environ.get("WEBHOOK_URL")


def _get_org_plan(org_id: str, db_session: object) -> str:
    """Look up the plan for an org from the database.

    Returns:
        The plan name string, defaulting to ``"free"`` if not found.
    """
    try:
        result = db_session.execute(
            text("SELECT plan FROM organizations WHERE org_id = :org_id"),
            {"org_id": org_id},
        )
        row = result.fetchone()
        return row[0] if row else "free"
    except Exception:
        logger.warning("Failed to look up plan for org %s, defaulting to free", org_id)
        return "free"


async def process_verified_event(
    event_data: Dict[str, Any],
    db_session: object,
) -> Optional[Dict[str, Any]]:
    """Process a verified event and deliver notifications if needed.

    Delivery is gated by the org's plan limits:
    - HTTP webhooks require ``webhook_alerts`` (pro+)
    - Slack alerts require ``slack_alerts`` (team+)

    Args:
        event_data: The verified event dict from Redis.
        db_session: A SQLAlchemy session for database writes.

    Returns:
        Alert record dict if an alert was created, None if skipped.
    """
    action = event_data.get("action", "pass")

    # Skip pass events — only alert on flag/block
    if action == "pass":
        return None

    agent_id = event_data.get("agent_id", "")
    execution_id = event_data.get("execution_id", "")
    org_id = event_data.get("org_id", DEFAULT_ORG)
    confidence_str = event_data.get("confidence", "")
    confidence = float(confidence_str) if confidence_str else None

    # Look up org plan for feature gating
    plan = _get_org_plan(org_id, db_session)
    plan_config = get_plan_config(plan)

    # Build alert record
    alert_id = str(uuid.uuid4())
    severity = "critical" if action == "block" else "high"

    # Parse check results for failure details
    checks_raw = event_data.get("checks", "{}")
    checks = json.loads(checks_raw) if isinstance(checks_raw, str) else checks_raw
    failure_types = [
        name for name, check in checks.items()
        if not check.get("passed", True)
    ]

    # --- HTTP webhook delivery (gated by plan) ---
    delivered = False
    delivery_attempts = 0
    response_status = None
    webhook_url = None

    if plan_config.webhook_alerts:
        webhook_url = get_webhook_url(agent_id)
        if webhook_url:
            payload = {
                "event": "verification.failed",
                "alert_id": alert_id,
                "agent_id": agent_id,
                "execution_id": execution_id,
                "confidence": confidence,
                "action": action,
                "failure_types": failure_types,
                "summary": f"Agent {agent_id} output {action}ed verification (confidence={confidence})",
            }
            delivered, response_status = await deliver(webhook_url, payload)
            delivery_attempts = 3 if not delivered else 1

    # --- Slack delivery (gated by plan) ---
    slack_delivered = False
    slack_url = None

    if plan_config.slack_alerts:
        slack_url = get_slack_webhook_url(agent_id)
        if slack_url:
            slack_payload = format_slack_message(
                alert_id=alert_id,
                agent_id=agent_id,
                execution_id=execution_id,
                action=action,
                severity=severity,
                confidence=confidence,
                failure_types=failure_types,
                dashboard_base_url=DASHBOARD_BASE_URL,
            )
            slack_delivered, _ = await deliver_slack(slack_url, slack_payload)

    # Combined delivery status: either channel succeeded
    any_delivered = delivered or slack_delivered

    # Write alert to database
    now = datetime.now(timezone.utc)
    db_session.execute(
        text("""
            INSERT INTO alerts (
                alert_id, execution_id, agent_id, org_id,
                alert_type, severity, delivered,
                webhook_url, delivery_attempts, last_attempt_at, response_status,
                created_at
            ) VALUES (
                :alert_id, :execution_id, :agent_id, :org_id,
                :alert_type, :severity, :delivered,
                :webhook_url, :delivery_attempts, :last_attempt_at, :response_status,
                :created_at
            )
        """),
        {
            "alert_id": alert_id,
            "execution_id": execution_id,
            "agent_id": agent_id,
            "org_id": org_id,
            "alert_type": f"verification_{action}",
            "severity": severity,
            "delivered": any_delivered,
            "webhook_url": webhook_url or slack_url,
            "delivery_attempts": delivery_attempts,
            "last_attempt_at": now if (webhook_url or slack_url) else None,
            "response_status": response_status,
            "created_at": now,
        },
    )
    db_session.commit()

    logger.info(
        "Alert %s created for execution %s (action=%s, webhook=%s, slack=%s)",
        alert_id,
        execution_id,
        action,
        delivered,
        slack_delivered,
    )

    return {
        "alert_id": alert_id,
        "execution_id": execution_id,
        "agent_id": agent_id,
        "action": action,
        "delivered": any_delivered,
        "slack_delivered": slack_delivered,
    }
