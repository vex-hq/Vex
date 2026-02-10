"""API route definitions for the AgentGuard Ingestion API.

Provides:
- ``GET /health`` -- service health check.
- ``POST /v1/ingest`` -- single-event ingestion.
- ``POST /v1/ingest/batch`` -- batch ingestion (up to 50 events).
"""

from typing import List

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from shared.models import IngestEvent, IngestResponse

from app.auth import verify_api_key

STREAM_KEY = "executions.raw"

router = APIRouter()


class SingleIngestResponse(BaseModel):
    """Response returned from the single-event ingestion endpoint."""

    accepted: int
    execution_id: str


class BatchIngestRequest(BaseModel):
    """Batch request with a hard cap of 50 events per payload.

    We define this locally rather than relying on the shared
    ``IngestBatchRequest`` so we can enforce the size limit at the
    API boundary via Pydantic validation.
    """

    events: List[IngestEvent] = Field(..., max_length=50)


@router.get("/health")
async def health_check():
    """Return service health status."""
    return {"status": "healthy"}


@router.post("/v1/ingest", status_code=202, response_model=SingleIngestResponse)
async def ingest_single(
    event: IngestEvent,
    request: Request,
    _api_key: str = Depends(verify_api_key),
):
    """Ingest a single execution event into the processing pipeline.

    The event is serialised and pushed to the ``executions.raw`` Redis
    Stream for downstream consumption by the storage worker.
    """
    redis = request.app.state.redis
    await redis.xadd(STREAM_KEY, {"data": event.model_dump_json()})
    return SingleIngestResponse(accepted=1, execution_id=event.execution_id)


@router.post("/v1/ingest/batch", status_code=202, response_model=IngestResponse)
async def ingest_batch(
    batch: BatchIngestRequest,
    request: Request,
    _api_key: str = Depends(verify_api_key),
):
    """Ingest a batch of execution events (max 50).

    Each event is individually pushed to the ``executions.raw`` Redis
    Stream. Returns the count of accepted events and their IDs.
    """
    redis = request.app.state.redis
    execution_ids: List[str] = []
    for event in batch.events:
        await redis.xadd(STREAM_KEY, {"data": event.model_dump_json()})
        execution_ids.append(event.execution_id)
    return IngestResponse(accepted=len(execution_ids), execution_ids=execution_ids)
