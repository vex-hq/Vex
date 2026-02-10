"""Core processing logic for the storage worker.

Handles writing execution trace payloads to S3 and execution metadata
to PostgreSQL. This module is intentionally decoupled from the Redis
consumer loop so it can be tested in isolation.
"""

import json
import logging

from sqlalchemy import text

from shared.models import IngestEvent

logger = logging.getLogger("agentguard.storage-worker")
S3_BUCKET = "agentguard-traces"


def process_event(
    event: IngestEvent,
    s3_client: object,
    db_session: object,
    org_id: str,
) -> None:
    """Process a single ingest event: write to S3 and PostgreSQL.

    Args:
        event: The validated ingest event to store.
        s3_client: A boto3 S3 client instance.
        db_session: A SQLAlchemy session for database writes.
        org_id: The organisation identifier for partitioning storage.

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

    # Write metadata to PostgreSQL
    db_session.execute(
        text("""
            INSERT INTO executions (
                execution_id, agent_id, org_id, timestamp,
                confidence, action, latency_ms, token_count,
                cost_estimate, trace_payload_ref, status, task, metadata
            ) VALUES (
                :execution_id, :agent_id, :org_id, :timestamp,
                :confidence, :action, :latency_ms, :token_count,
                :cost_estimate, :trace_payload_ref, :status, :task, :metadata
            )
        """),
        {
            "execution_id": event.execution_id,
            "agent_id": event.agent_id,
            "org_id": org_id,
            "timestamp": event.timestamp,
            "confidence": None,
            "action": "pass",
            "latency_ms": event.latency_ms,
            "token_count": event.token_count,
            "cost_estimate": None,
            "trace_payload_ref": f"s3://{S3_BUCKET}/{s3_key}",
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
