"""Shared Pydantic models for AgentGuard backend services.

These models define the API contract between the SDK and backend services.
They mirror SDK types (StepRecord, ExecutionEvent -> IngestEvent) for
serialization compatibility, but live in a separate package so backend
services do not depend on the SDK.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class StepRecord(BaseModel):
    """An intermediate agent step (tool call, LLM call, etc.).

    Mirrors the SDK's StepRecord for serialization compatibility.
    """

    step_type: str
    name: str
    input: Any = None
    output: Any = None
    duration_ms: Optional[float] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IngestEvent(BaseModel):
    """Telemetry payload received from the SDK.

    Mirrors the SDK's ExecutionEvent. This is the primary ingest format
    for both async (ingestion) and sync (verification) paths.
    """

    execution_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str
    task: Optional[str] = None
    input: Any
    output: Any
    steps: List[StepRecord] = Field(default_factory=list)
    token_count: Optional[int] = None
    latency_ms: Optional[float] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ground_truth: Any = None
    schema_definition: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class IngestBatchRequest(BaseModel):
    """A batch of ingest events submitted together."""

    events: List[IngestEvent]


class IngestResponse(BaseModel):
    """Response returned from ingestion endpoints."""

    accepted: int
    execution_ids: List[str] = Field(default_factory=list)


class CheckResult(BaseModel):
    """Result of a single verification check (schema, hallucination, etc.)."""

    check_type: str
    score: float
    passed: bool
    details: Dict[str, Any] = Field(default_factory=dict)


class VerifyRequest(IngestEvent):
    """Request payload for synchronous verification.

    Inherits from IngestEvent -- same payload structure, but semantically
    indicates the caller expects a synchronous verification response.
    """

    pass


class VerifyResponse(BaseModel):
    """Response from synchronous verification."""

    execution_id: str
    confidence: Optional[float] = None
    action: str = "pass"
    output: Any = None
    corrections: Optional[List[Dict[str, Any]]] = None
    checks: Dict[str, CheckResult] = Field(default_factory=dict)
