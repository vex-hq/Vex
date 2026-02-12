"""Core processing logic for the alert service.

Receives verified events, filters for flag/block actions, resolves
webhook URLs, delivers notifications, and records delivery status
in the alerts table.

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

from app.webhook import deliver

logger = logging.getLogger("agentguard.alert-service")

DEFAULT_ORG = "default"


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


async def process_verified_event(
    event_data: Dict[str, Any],
    db_session: object,
) -> Optional[Dict[str, Any]]:
    """Process a verified event and deliver webhook if needed.

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
    confidence_str = event_data.get("confidence", "")
    confidence = float(confidence_str) if confidence_str else None

    webhook_url = get_webhook_url(agent_id)

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

    # Deliver webhook if URL is configured
    delivered = False
    delivery_attempts = 0
    response_status = None

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
            "org_id": DEFAULT_ORG,
            "alert_type": f"verification_{action}",
            "severity": severity,
            "delivered": delivered,
            "webhook_url": webhook_url,
            "delivery_attempts": delivery_attempts,
            "last_attempt_at": now if webhook_url else None,
            "response_status": response_status,
            "created_at": now,
        },
    )
    db_session.commit()

    logger.info(
        "Alert %s created for execution %s (action=%s, delivered=%s)",
        alert_id,
        execution_id,
        action,
        delivered,
    )

    return {
        "alert_id": alert_id,
        "execution_id": execution_id,
        "agent_id": agent_id,
        "action": action,
        "delivered": delivered,
    }
