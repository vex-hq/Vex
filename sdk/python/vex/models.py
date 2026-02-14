from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class ThresholdConfig(BaseModel):
    pass_threshold: float = 0.8
    flag_threshold: float = 0.5
    block_threshold: float = 0.3

    @model_validator(mode="after")
    def validate_threshold_order(self) -> "ThresholdConfig":
        if not (self.block_threshold < self.flag_threshold < self.pass_threshold):
            raise ValueError(
                "Thresholds must satisfy: block < flag < pass. "
                f"Got block={self.block_threshold}, flag={self.flag_threshold}, "
                f"pass={self.pass_threshold}"
            )
        return self


class ConversationTurn(BaseModel):
    """A single turn in a multi-turn conversation.

    Used by Session to accumulate conversation history for cross-turn
    verification (hallucination, drift, coherence).
    """

    sequence_number: int
    input: Any = None
    output: Any = None
    task: Optional[str] = None


class StepRecord(BaseModel):
    step_type: str  # "tool_call", "llm", "custom"
    name: str
    input: Any = None
    output: Any = None
    duration_ms: Optional[float] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExecutionEvent(BaseModel):
    execution_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: Optional[str] = None
    parent_execution_id: Optional[str] = None
    sequence_number: Optional[int] = None
    agent_id: str
    task: Optional[str] = None
    input: Any
    output: Any
    steps: List[StepRecord] = Field(default_factory=list)
    token_count: Optional[int] = None
    cost_estimate: Optional[float] = None
    latency_ms: Optional[float] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ground_truth: Any = None
    schema_definition: Optional[Dict[str, Any]] = None
    conversation_history: Optional[List[ConversationTurn]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VexResult(BaseModel):
    output: Any
    confidence: Optional[float] = None
    action: str = "pass"  # "pass" | "flag" | "block"
    corrections: Optional[List[Dict[str, Any]]] = None
    execution_id: str
    verification: Optional[Dict[str, Any]] = None
    corrected: bool = False
    original_output: Optional[Any] = None
