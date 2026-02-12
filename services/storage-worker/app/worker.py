"""Core processing logic for the storage worker.

Handles writing execution trace payloads to S3 and execution metadata
to PostgreSQL. Returns a stored-event notification dict that the caller
can publish to the ``executions.stored`` Redis Stream for downstream
consumers (e.g. the real-time WebSocket service).

Also processes verified events by writing check_results rows and
updating execution confidence/action.

This module is intentionally decoupled from the Redis consumer loop so
it can be tested in isolation.
"""

import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy import text

from shared.models import IngestEvent

logger = logging.getLogger("agentguard.storage-worker")
S3_BUCKET = "agentguard-traces"
STORED_STREAM_KEY = "executions.stored"
VERIFIED_STREAM_KEY = "executions.verified"


def process_event(
    event: IngestEvent,
    s3_client: object,
    db_session: object,
    org_id: str,
) -> Dict[str, Any]:
    """Process a single ingest event: write to S3 and PostgreSQL.

    Args:
        event: The validated ingest event to store.
        s3_client: A boto3 S3 client instance.
        db_session: A SQLAlchemy session for database writes.
        org_id: The organisation identifier for partitioning storage.

    Returns:
        A dict representing the stored execution notification, suitable
        for publishing to the ``executions.stored`` Redis Stream.

    The S3 key is structured as:
        {org_id}/{agent_id}/{date}/{execution_id}.json

    The PostgreSQL row includes execution metadata and a reference
    back to the full trace payload in S3.
    """
    date_str = event.timestamp.strftime("%Y-%m-%d")
    s3_key = f"{org_id}/{event.agent_id}/{date_str}/{event.execution_id}.json"

    # Write full payload to S3
    payload = event.model_dump_json()
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=payload,
        ContentType="application/json",
    )

    trace_ref = f"s3://{S3_BUCKET}/{s3_key}"

    # Write metadata to PostgreSQL
    db_session.execute(
        text("""
            INSERT INTO executions (
                execution_id, agent_id, org_id, timestamp,
                session_id, parent_execution_id, sequence_number,
                confidence, action, latency_ms, token_count,
                cost_estimate, trace_payload_ref, status, task, metadata
            ) VALUES (
                :execution_id, :agent_id, :org_id, :timestamp,
                :session_id, :parent_execution_id, :sequence_number,
                :confidence, :action, :latency_ms, :token_count,
                :cost_estimate, :trace_payload_ref, :status, :task, :metadata
            )
        """),
        {
            "execution_id": event.execution_id,
            "agent_id": event.agent_id,
            "org_id": org_id,
            "timestamp": event.timestamp,
            "session_id": event.session_id,
            "parent_execution_id": event.parent_execution_id,
            "sequence_number": event.sequence_number,
            "confidence": None,
            "action": "pass",
            "latency_ms": event.latency_ms,
            "token_count": event.token_count,
            "cost_estimate": event.cost_estimate,
            "trace_payload_ref": trace_ref,
            "status": "pass",
            "task": event.task,
            "metadata": json.dumps(event.metadata),
        },
    )
    db_session.commit()
    logger.info(
        "Stored execution %s for agent %s",
        event.execution_id,
        event.agent_id,
    )

    return {
        "execution_id": event.execution_id,
        "agent_id": event.agent_id,
        "org_id": org_id,
        "timestamp": event.timestamp.isoformat(),
        "session_id": event.session_id,
        "parent_execution_id": event.parent_execution_id,
        "sequence_number": event.sequence_number,
        "action": "pass",
        "latency_ms": event.latency_ms,
        "token_count": event.token_count,
        "cost_estimate": event.cost_estimate,
        "trace_payload_ref": trace_ref,
    }


def process_verified_event(
    event_data: Dict[str, Any],
    db_session: object,
) -> Dict[str, Any]:
    """Process a verified event: write check_results and update execution.

    Args:
        event_data: The verified event dict from Redis containing
            execution_id, agent_id, confidence, action, and checks.
        db_session: A SQLAlchemy session for database writes.

    Returns:
        A dict representing the updated notification for the
        ``executions.stored`` stream.
    """
    execution_id = event_data["execution_id"]
    agent_id = event_data.get("agent_id", "")
    confidence_str = event_data.get("confidence", "")
    confidence = float(confidence_str) if confidence_str else None
    action = event_data.get("action", "pass")
    checks_raw = event_data.get("checks", "{}")
    checks = json.loads(checks_raw) if isinstance(checks_raw, str) else checks_raw

    # Extract correction fields (defaults to False when absent)
    corrected_str = event_data.get("corrected", "False")
    corrected = corrected_str == "True" or corrected_str is True

    correction_attempts_raw = event_data.get("correction_attempts")
    correction_attempts = (
        json.loads(correction_attempts_raw)
        if isinstance(correction_attempts_raw, str) and correction_attempts_raw
        else correction_attempts_raw
    )

    original_output_raw = event_data.get("original_output")
    original_output = original_output_raw
    if isinstance(original_output_raw, str) and original_output_raw:
        try:
            original_output = json.loads(original_output_raw)
        except (json.JSONDecodeError, ValueError):
            original_output = original_output_raw

    # Build correction metadata for potential future storage
    correction_metadata = None  # type: Optional[str]
    if corrected:
        correction_metadata = json.dumps({
            "correction_attempts": correction_attempts or [],
            "original_output": original_output,
        })

    # Update execution row first — if the row doesn't exist yet
    # (raw consumer hasn't created it), we skip check_results to
    # avoid FK constraint violations and signal for retry.
    result = db_session.execute(
        text("""
            UPDATE executions
            SET confidence = :confidence, action = :action, corrected = :corrected
            WHERE execution_id = :execution_id
        """),
        {
            "execution_id": execution_id,
            "confidence": confidence,
            "action": action,
            "corrected": corrected,
        },
    )
    row_updated = result.rowcount > 0

    if not row_updated:
        logger.warning(
            "UPDATE for execution %s affected 0 rows — row may not exist yet",
            execution_id,
        )
        db_session.rollback()
    else:
        # Write check_results only after confirming the execution exists
        for check_name, check_data in checks.items():
            db_session.execute(
                text("""
                    INSERT INTO check_results (
                        execution_id, check_type, score, passed, details
                    ) VALUES (
                        :execution_id, :check_type, :score, :passed, :details
                    )
                """),
                {
                    "execution_id": execution_id,
                    "check_type": check_data.get("check_type", check_name),
                    "score": check_data.get("score"),
                    "passed": check_data.get("passed", True),
                    "details": json.dumps(check_data.get("details", {})),
                },
            )
        db_session.commit()
    logger.info(
        "Stored verified results for execution %s (action=%s, confidence=%s, corrected=%s, row_updated=%s)",
        execution_id,
        action,
        confidence,
        corrected,
        row_updated,
    )

    return {
        "execution_id": execution_id,
        "agent_id": agent_id,
        "action": action,
        "confidence": confidence,
        "checks_stored": len(checks),
        "corrected": corrected,
        "row_updated": row_updated,
    }
