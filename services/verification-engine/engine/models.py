"""Pydantic models for verification results and configuration."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ConversationTurn(BaseModel):
    """A single turn in a multi-turn conversation."""

    sequence_number: int
    input: Any = None
    output: Any = None
    task: Optional[str] = None


class CheckResult(BaseModel):
    """Result of a single verification check."""

    check_type: str  # "schema", "hallucination", "drift", "coherence"
    score: Optional[float] = None  # 0-1, None if unable to verify
    passed: bool
    details: Dict[str, Any] = Field(default_factory=dict)


class VerificationConfig(BaseModel):
    """Configuration for verification thresholds and check weights."""

    weights: Dict[str, float] = Field(
        default_factory=lambda: {
            "schema": 0.3,
            "hallucination": 0.4,
            "drift": 0.3,
        }
    )
    pass_threshold: float = 0.8
    flag_threshold: float = 0.5


class CorrectionAttempt(BaseModel):
    """Record of a single correction attempt within the cascade."""

    layer: int  # 1, 2, or 3
    layer_name: str  # "repair", "constrained_regen", "full_reprompt"
    input_action: str  # action that triggered correction
    input_confidence: Optional[float] = None
    corrected_output: Any = None
    verification: Optional[Dict[str, Any]] = None
    model_used: str = ""
    latency_ms: float = 0.0
    success: bool = False


class CorrectionResult(BaseModel):
    """Full correction cascade outcome."""

    corrected: bool = False
    final_output: Any = None
    attempts: List[CorrectionAttempt] = Field(default_factory=list)
    total_latency_ms: float = 0.0
    escalation_path: List[int] = Field(default_factory=list)


class VerificationResult(BaseModel):
    """Composite result from the full verification pipeline."""

    confidence: Optional[float] = None  # weighted composite, None if all checks failed
    action: str = "pass"  # "pass" | "flag" | "block"
    checks: Dict[str, CheckResult] = Field(default_factory=dict)
    correction: Optional[CorrectionResult] = None
