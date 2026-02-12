"""Core processing logic for the async verification worker.

Receives an IngestEvent, runs the verification engine pipeline, and
produces a verified event dict suitable for publishing to the
``executions.verified`` Redis Stream.

This module is intentionally decoupled from the Redis consumer loop so
it can be tested in isolation.
"""

import json
import logging
from typing import Any, Dict

from engine.pipeline import verify
from shared.models import IngestEvent

logger = logging.getLogger("agentguard.async-worker")

VERIFIED_STREAM_KEY = "executions.verified"


async def process_event(event: IngestEvent) -> Dict[str, Any]:
    """Run verification on an ingest event and return a verified event dict.

    Args:
        event: The validated ingest event to verify.

    Returns:
        A dict representing the verified event, suitable for publishing
        to the ``executions.verified`` Redis Stream.
    """
    try:
        result = await verify(
            output=event.output,
            task=event.task,
            schema=event.schema_definition,
            ground_truth=event.ground_truth,
            conversation_history=event.conversation_history,
        )

        checks_data = {}
        for name, check in result.checks.items():
            checks_data[name] = {
                "check_type": check.check_type,
                "score": check.score,
                "passed": check.passed,
                "details": check.details,
            }

        return {
            "execution_id": event.execution_id,
            "agent_id": event.agent_id,
            "confidence": str(result.confidence) if result.confidence is not None else "",
            "action": result.action,
            "checks": json.dumps(checks_data),
        }
    except Exception:
        logger.error(
            "Verification failed for event %s; returning pass-through",
            event.execution_id,
            exc_info=True,
        )
        return {
            "execution_id": event.execution_id,
            "agent_id": event.agent_id,
            "confidence": "",
            "action": "pass",
            "checks": "{}",
        }
