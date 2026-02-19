"""Load guardrail rules from the database for a given org and agent.

Loads both agent-specific rules and org-wide rules (agent_id IS NULL),
merging them into a single list. Uses a lightweight SQLAlchemy connection
that is created lazily and reused across calls.
"""

import logging
import os
from typing import Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from engine.models import GuardrailRule

logger = logging.getLogger("agentguard.sync-gateway.guardrails_loader")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://agentguard:agentguard_dev@localhost:5432/agentguard",
)

_engine = None
_SessionLocal = None


def _get_session() -> Session:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_engine(DATABASE_URL, pool_size=2, pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=_engine)
    return _SessionLocal()


def load_guardrails(org_id: str, agent_id: str) -> List[GuardrailRule]:
    """Load enabled guardrail rules for an org + agent from the database.

    Returns agent-specific rules and org-wide rules (where agent_id IS NULL),
    with agent-specific rules taking precedence.

    Args:
        org_id: The organisation identifier.
        agent_id: The agent identifier.

    Returns:
        List of GuardrailRule objects. Empty list if none configured or on error.
    """
    try:
        session = _get_session()
        try:
            result = session.execute(
                text("""
                    SELECT id, name, rule_type, condition, action, enabled, agent_id
                    FROM guardrails
                    WHERE org_id = :org_id
                      AND (agent_id = :agent_id OR agent_id IS NULL)
                      AND enabled = true
                    ORDER BY agent_id NULLS LAST, created_at ASC
                """),
                {"org_id": org_id, "agent_id": agent_id},
            )
            rows = result.fetchall()
        finally:
            session.close()

        rules = []
        for row in rows:
            condition = row[3]
            if isinstance(condition, str):
                import json
                condition = json.loads(condition)

            rules.append(GuardrailRule(
                id=row[0],
                name=row[1],
                rule_type=row[2],
                condition=condition,
                action=row[4],
                enabled=row[5],
            ))

        return rules

    except Exception:
        logger.warning(
            "Failed to load guardrails for org=%s agent=%s, returning empty",
            org_id,
            agent_id,
            exc_info=True,
        )
        return []
