# Phase 3: Correction Cascade — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a graduated self-correction cascade that automatically fixes failed agent outputs, re-verifying each correction before accepting it.

**Architecture:** When verification fails and `correction="cascade"`, the sync gateway runs a correction loop: select starting layer based on failure severity → correct with LLM → re-verify → if pass, return corrected output; if fail, escalate to next layer. Max 2 attempts. All correction logic lives in `engine/correction.py`, orchestrated by the gateway.

**Tech Stack:** Python 3.9+ (typing compat), Pydantic v2, LiteLLM, FastAPI, httpx, PostgreSQL/Alembic, pytest/pytest-asyncio

**Design Doc:** `docs/plans/2026-02-11-phase3-correction-cascade.md`

---

## Build Order & Dependencies

```
Task 1:  DB Migration 006                              ← no deps
Task 2:  Engine models (CorrectionAttempt, etc.)        ← no deps
Task 3:  Engine correction module (select_layer, L1-3)  ← depends T2
Task 4:  Shared models (VerifyResponse update)          ← no deps
Task 5:  Gateway orchestration (correction loop)        ← depends T2, T3, T4
Task 6:  Storage worker (persist corrected flag)        ← depends T1, T4
Task 7:  SDK transport (dual timeout, forwarding)       ← depends T4
Task 8:  SDK models + guard client                      ← depends T7
Task 9:  Dashboard (correction UI)                      ← depends T1, T6
Task 10: Integration tests                              ← depends T5-T8
Task 11: Live LLM test                                  ← depends all
```

---

## Task 1: DB Migration 006

**Files:**
- Create: `services/migrations/alembic/versions/006_add_correction_column.py`

### Step 1: Write the migration

```python
"""Add correction tracking column to executions.

Revision ID: 006
Revises: 005
Create Date: 2026-02-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "executions",
        sa.Column("corrected", sa.Boolean, server_default="false", nullable=False),
    )
    op.create_index(
        "idx_executions_corrected",
        "executions",
        ["org_id", "corrected"],
        postgresql_where=sa.text("corrected = TRUE"),
    )


def downgrade() -> None:
    op.drop_index("idx_executions_corrected", table_name="executions")
    op.drop_column("executions", "corrected")
```

### Step 2: Verify migration syntax

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && python3 -c "import importlib.util; spec = importlib.util.spec_from_file_location('m', 'services/migrations/alembic/versions/006_add_correction_column.py'); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); print('OK:', mod.revision, '->', mod.down_revision)"`
Expected: `OK: 006 -> 005`

### Step 3: Commit

```bash
git add services/migrations/alembic/versions/006_add_correction_column.py
git commit -m "feat(migration): add corrected column to executions table (006)"
```

---

## Task 2: Engine Models — CorrectionAttempt, CorrectionResult

**Files:**
- Modify: `services/verification-engine/engine/models.py`
- Create: `services/verification-engine/tests/test_correction_models.py`

### Step 1: Write the failing tests

Create `services/verification-engine/tests/test_correction_models.py`:

```python
"""Tests for correction-related engine models."""

from engine.models import (
    CheckResult,
    CorrectionAttempt,
    CorrectionResult,
    VerificationResult,
)


def test_correction_attempt_creation():
    attempt = CorrectionAttempt(
        layer=1,
        layer_name="repair",
        input_action="flag",
        input_confidence=0.6,
        corrected_output="fixed output",
        verification={"confidence": 0.9, "action": "pass"},
        model_used="gpt-4o-mini",
        latency_ms=340.0,
        success=True,
    )
    assert attempt.layer == 1
    assert attempt.layer_name == "repair"
    assert attempt.success is True
    assert attempt.latency_ms == 340.0


def test_correction_result_creation():
    attempt = CorrectionAttempt(
        layer=2,
        layer_name="constrained_regen",
        input_action="block",
        input_confidence=0.3,
        corrected_output="regenerated output",
        verification=None,
        model_used="gpt-4o",
        latency_ms=1200.0,
        success=True,
    )
    result = CorrectionResult(
        corrected=True,
        final_output="regenerated output",
        attempts=[attempt],
        total_latency_ms=1200.0,
        escalation_path=[2],
    )
    assert result.corrected is True
    assert len(result.attempts) == 1
    assert result.escalation_path == [2]


def test_verification_result_with_correction():
    vr = VerificationResult(
        confidence=0.9,
        action="pass",
        checks={
            "schema": CheckResult(check_type="schema", score=1.0, passed=True),
        },
        correction=CorrectionResult(
            corrected=True,
            final_output="fixed",
            attempts=[],
            total_latency_ms=500.0,
            escalation_path=[1],
        ),
    )
    assert vr.correction is not None
    assert vr.correction.corrected is True


def test_verification_result_without_correction():
    """Backward compat — correction defaults to None."""
    vr = VerificationResult(confidence=0.9, action="pass")
    assert vr.correction is None
```

### Step 2: Run tests to verify they fail

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && python3 -m pytest services/verification-engine/tests/test_correction_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'CorrectionAttempt'`

### Step 3: Implement the models

Add to `services/verification-engine/engine/models.py` — append after `VerificationConfig`:

```python
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
```

Also add `correction` field to `VerificationResult`:

```python
class VerificationResult(BaseModel):
    """Composite result from the full verification pipeline."""

    confidence: Optional[float] = None
    action: str = "pass"
    checks: Dict[str, CheckResult] = Field(default_factory=dict)
    correction: Optional[CorrectionResult] = None
```

### Step 4: Run tests to verify they pass

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && python3 -m pytest services/verification-engine/tests/test_correction_models.py -v`
Expected: 4 PASSED

### Step 5: Run ALL existing engine tests to verify no regression

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && python3 -m pytest services/verification-engine/tests/ -v`
Expected: All existing tests + 4 new = PASS

### Step 6: Commit

```bash
git add services/verification-engine/engine/models.py services/verification-engine/tests/test_correction_models.py
git commit -m "feat(engine): add CorrectionAttempt, CorrectionResult models and correction field on VerificationResult"
```

---

## Task 3: Engine Correction Module

**Files:**
- Create: `services/verification-engine/engine/correction.py`
- Create: `services/verification-engine/tests/test_correction.py`

### Step 1: Write the failing tests

Create `services/verification-engine/tests/test_correction.py`:

```python
"""Tests for the correction cascade module."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from engine.models import CheckResult, CorrectionAttempt, VerificationResult
from engine.correction import (
    LAYER_NAMES,
    correct,
    format_check_failures,
    select_layer,
)


# --- select_layer tests ---


def test_select_layer_schema_only_failure():
    """Schema-only failure → Layer 1 (Repair)."""
    result = VerificationResult(
        confidence=0.6,
        action="flag",
        checks={
            "schema": CheckResult(check_type="schema", score=0.0, passed=False,
                                  details={"errors": ["missing field"]}),
            "hallucination": CheckResult(check_type="hallucination", score=1.0, passed=True),
            "drift": CheckResult(check_type="drift", score=0.9, passed=True),
        },
    )
    assert select_layer(result) == 1


def test_select_layer_mild_failure():
    """Confidence > 0.5 → Layer 1."""
    result = VerificationResult(
        confidence=0.55,
        action="flag",
        checks={
            "schema": CheckResult(check_type="schema", score=1.0, passed=True),
            "hallucination": CheckResult(check_type="hallucination", score=0.4, passed=False),
            "drift": CheckResult(check_type="drift", score=0.9, passed=True),
        },
    )
    assert select_layer(result) == 1


def test_select_layer_moderate_failure():
    """Confidence between 0.3 and 0.5 → Layer 2."""
    result = VerificationResult(
        confidence=0.4,
        action="block",
        checks={
            "hallucination": CheckResult(check_type="hallucination", score=0.2, passed=False),
        },
    )
    assert select_layer(result) == 2


def test_select_layer_severe_failure():
    """Confidence <= 0.3 → Layer 3."""
    result = VerificationResult(
        confidence=0.2,
        action="block",
        checks={
            "hallucination": CheckResult(check_type="hallucination", score=0.0, passed=False),
            "drift": CheckResult(check_type="drift", score=0.1, passed=False),
        },
    )
    assert select_layer(result) == 3


def test_select_layer_none_confidence():
    """None confidence → Layer 3 (severe)."""
    result = VerificationResult(
        confidence=None,
        action="block",
        checks={},
    )
    assert select_layer(result) == 3


# --- format_check_failures tests ---


def test_format_check_failures():
    checks = {
        "schema": CheckResult(
            check_type="schema", score=0.0, passed=False,
            details={"errors": ["'revenue' is a required property"]},
        ),
        "hallucination": CheckResult(
            check_type="hallucination", score=1.0, passed=True,
        ),
    }
    formatted = format_check_failures(checks)
    assert "schema" in formatted
    assert "revenue" in formatted
    assert "hallucination" not in formatted  # passed, not included


# --- correct() tests ---


@pytest.mark.asyncio
async def test_correct_layer1_repair():
    """Layer 1 should call LLM with repair prompt and return corrected output."""
    llm_response = {"corrected_output": '{"revenue": 5200000}'}

    with patch("engine.correction.call_llm", new_callable=AsyncMock, return_value=llm_response):
        result = await correct(
            layer=1,
            output='{"revnue": 5200000}',
            task="Generate financial report",
            checks={
                "schema": CheckResult(
                    check_type="schema", score=0.0, passed=False,
                    details={"errors": ["'revenue' is a required property"]},
                ),
            },
        )

    assert result.layer == 1
    assert result.layer_name == "repair"
    assert result.corrected_output is not None


@pytest.mark.asyncio
async def test_correct_layer2_constrained_regen():
    """Layer 2 should regenerate with constraints, NOT seeing the failed output."""
    llm_response = {"output": "Revenue is $5.2 billion for Q3 2025."}

    with patch("engine.correction.call_llm", new_callable=AsyncMock, return_value=llm_response) as mock_llm:
        result = await correct(
            layer=2,
            output="Revenue is $999 trillion!",  # hallucinated
            task="Summarize Q3 earnings",
            checks={},
            ground_truth={"revenue": "$5.2B"},
        )

    assert result.layer == 2
    assert result.layer_name == "constrained_regen"
    assert result.corrected_output is not None
    # Layer 2 prompt should NOT contain the failed output
    call_args = mock_llm.call_args
    prompt_text = call_args[0][0] if call_args[0] else call_args[1].get("prompt", "")
    assert "$999 trillion" not in prompt_text


@pytest.mark.asyncio
async def test_correct_layer3_full_reprompt():
    """Layer 3 should include explicit failure feedback."""
    llm_response = {"output": "I apologize, the revenue figure is $5.2B."}

    with patch("engine.correction.call_llm", new_callable=AsyncMock, return_value=llm_response) as mock_llm:
        result = await correct(
            layer=3,
            output="bad output",
            task="Financial summary",
            checks={
                "hallucination": CheckResult(
                    check_type="hallucination", score=0.1, passed=False,
                    details={"ungrounded": ["Revenue is $999T"]},
                ),
            },
            ground_truth={"revenue": "$5.2B"},
        )

    assert result.layer == 3
    assert result.layer_name == "full_reprompt"
    # Layer 3 prompt should contain failure details
    call_args = mock_llm.call_args
    prompt_text = call_args[0][0] if call_args[0] else call_args[1].get("prompt", "")
    assert "FAILED" in prompt_text or "WRONG" in prompt_text or "failed" in prompt_text


@pytest.mark.asyncio
async def test_correct_llm_timeout_returns_failure():
    """LLM timeout → correction returns None corrected_output."""
    with patch("engine.correction.call_llm", new_callable=AsyncMock, return_value=None):
        result = await correct(
            layer=1,
            output="broken",
            task="task",
            checks={},
        )

    assert result.corrected_output is None
    assert result.success is False


@pytest.mark.asyncio
async def test_correct_llm_malformed_response():
    """LLM returns unexpected structure → treated as failure."""
    with patch("engine.correction.call_llm", new_callable=AsyncMock, return_value={"unexpected": "data"}):
        result = await correct(
            layer=2,
            output="broken",
            task="task",
            checks={},
        )

    # Should still return a CorrectionAttempt even if output extraction fails
    assert isinstance(result, CorrectionAttempt)
```

### Step 2: Run tests to verify they fail

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && python3 -m pytest services/verification-engine/tests/test_correction.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.correction'`

### Step 3: Implement the correction module

Create `services/verification-engine/engine/correction.py`:

```python
"""Correction cascade — graduated self-correction of failed agent outputs.

Provides three correction layers of increasing power:

1. **Repair** (small model) — surgical fix of specific errors (schema, format).
2. **Constrained Regeneration** (strong model) — generates fresh output with
   constraints derived from task, schema, ground truth, and conversation history.
   Does NOT see the failed output to avoid anchoring.
3. **Full Re-prompt** (strong model) — regenerates with explicit failure
   feedback.  Last resort before blocking.

Each layer is stateless.  The sync gateway orchestrates the cascade loop,
calling ``correct()`` then re-running ``verify()`` for each attempt.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from engine.conversation_utils import format_history
from engine.llm_client import call_llm
from engine.models import CheckResult, ConversationTurn, CorrectionAttempt

logger = logging.getLogger("agentguard.verification-engine.correction")

LAYER_NAMES = {1: "repair", 2: "constrained_regen", 3: "full_reprompt"}

# Model selection: Layer 1 uses fast/cheap model, Layers 2-3 use strong model
DEFAULT_REPAIR_MODEL = "gpt-4o-mini"
DEFAULT_STRONG_MODEL = "gpt-4o"


def _get_repair_model() -> str:
    return os.environ.get("CORRECTION_REPAIR_MODEL", DEFAULT_REPAIR_MODEL)


def _get_strong_model() -> str:
    return os.environ.get("CORRECTION_STRONG_MODEL", DEFAULT_STRONG_MODEL)


def select_layer(result: "VerificationResult") -> int:
    """Select the starting correction layer based on failure severity.

    Args:
        result: The failed verification result.

    Returns:
        Layer number: 1 (repair), 2 (constrained regen), or 3 (full re-prompt).
    """
    from engine.models import VerificationResult  # avoid circular import

    checks = result.checks

    # Schema-only failure → Layer 1 (Repair)
    schema = checks.get("schema")
    non_schema_failed = any(
        not c.passed for name, c in checks.items() if name != "schema"
    )
    if schema and not schema.passed and not non_schema_failed:
        return 1

    # Mild failure (confidence > 0.5) → Layer 1
    if result.confidence is not None and result.confidence > 0.5:
        return 1

    # Moderate failure (confidence > 0.3) → Layer 2
    if result.confidence is not None and result.confidence > 0.3:
        return 2

    # Severe failure → Layer 3
    return 3


def format_check_failures(checks: Dict[str, CheckResult]) -> str:
    """Format failed checks into a human-readable error description.

    Only includes checks that failed (passed=False).
    """
    parts: List[str] = []
    for name, check in checks.items():
        if not check.passed:
            details_str = json.dumps(check.details, default=str) if check.details else ""
            parts.append(
                f"- {name} (score={check.score}): {details_str}"
            )
    return "\n".join(parts) if parts else "No specific errors identified."


async def correct(
    layer: int,
    output: Any,
    task: Optional[str] = None,
    checks: Optional[Dict[str, CheckResult]] = None,
    schema: Optional[Dict[str, Any]] = None,
    ground_truth: Any = None,
    conversation_history: Optional[List[ConversationTurn]] = None,
    input_data: Any = None,
) -> CorrectionAttempt:
    """Execute a single correction attempt at the given layer.

    Args:
        layer: Which correction layer to use (1, 2, or 3).
        output: The original failed output (used by L1 and L3, NOT L2).
        task: Task description for context.
        checks: Failed check results for error details.
        schema: JSON Schema definition for structure constraints.
        ground_truth: Reference data for factual constraints.
        conversation_history: Prior turns for conversation context.
        input_data: Original input that produced the output.

    Returns:
        CorrectionAttempt with the corrected output (or None on failure).
    """
    checks = checks or {}
    layer_name = LAYER_NAMES.get(layer, "unknown")
    start = time.monotonic()

    if layer == 1:
        corrected_output, model = await _layer1_repair(output, checks)
    elif layer == 2:
        corrected_output, model = await _layer2_constrained_regen(
            task, checks, schema, ground_truth, conversation_history, input_data,
        )
    else:
        corrected_output, model = await _layer3_full_reprompt(
            output, task, checks, schema, ground_truth, conversation_history, input_data,
        )

    elapsed_ms = (time.monotonic() - start) * 1000.0

    return CorrectionAttempt(
        layer=layer,
        layer_name=layer_name,
        input_action="",  # filled by gateway
        input_confidence=None,  # filled by gateway
        corrected_output=corrected_output,
        verification=None,  # filled after re-verify
        model_used=model,
        latency_ms=elapsed_ms,
        success=corrected_output is not None,
    )


async def _layer1_repair(
    output: Any,
    checks: Dict[str, CheckResult],
) -> tuple:
    """Layer 1: Surgical repair of specific errors."""
    model = _get_repair_model()
    output_str = output if isinstance(output, str) else json.dumps(output, default=str)
    failures = format_check_failures(checks)

    prompt = (
        "You are a data repair tool. Fix ONLY the specific errors listed below.\n"
        "Do NOT change content, meaning, or add information. Make the minimum "
        "edit needed to fix each error.\n\n"
        f"ORIGINAL OUTPUT:\n{output_str}\n\n"
        f"ERRORS TO FIX:\n{failures}\n\n"
        "Return JSON with this schema:\n"
        '{"corrected_output": "<the fixed output>"}\n\n'
        "If the original output is JSON, the corrected_output should also be valid JSON. "
        "Return ONLY the JSON response."
    )

    system = (
        "You are a precise data repair tool. You fix exactly the errors specified "
        "and make no other changes. Respond only in valid JSON."
    )

    result = await call_llm(prompt, system=system)
    if result is None:
        return None, model

    corrected = result.get("corrected_output")
    if corrected is None:
        corrected = result.get("output")

    # Try to parse if it looks like JSON
    if isinstance(corrected, str):
        try:
            corrected = json.loads(corrected)
        except (json.JSONDecodeError, TypeError):
            pass  # keep as string

    return corrected, model


async def _layer2_constrained_regen(
    task: Optional[str],
    checks: Dict[str, CheckResult],
    schema: Optional[Dict[str, Any]],
    ground_truth: Any,
    conversation_history: Optional[List[ConversationTurn]],
    input_data: Any,
) -> tuple:
    """Layer 2: Constrained regeneration — generate fresh output WITHOUT seeing the failed output."""
    model = _get_strong_model()

    constraints: List[str] = []
    if schema:
        constraints.append(f"You MUST follow this schema: {json.dumps(schema)}")
    if ground_truth:
        truth_str = ground_truth if isinstance(ground_truth, str) else json.dumps(ground_truth, default=str)
        constraints.append(f"Ground truth facts (do NOT contradict): {truth_str}")

    constraints_str = "\n".join(f"- {c}" for c in constraints) if constraints else "None specified."

    history_section = ""
    if conversation_history:
        history_str = format_history(conversation_history)
        history_section = f"\nCONVERSATION HISTORY:\n{history_str}\n"

    input_section = ""
    if input_data is not None:
        input_str = input_data if isinstance(input_data, str) else json.dumps(input_data, default=str)
        input_section = f"\nINPUT CONTEXT:\n{input_str}\n"

    prompt = (
        "You are a reliable AI assistant. Generate a response for the following task.\n\n"
        f"TASK: {task or 'Not specified'}\n"
        f"{input_section}"
        f"\nCONSTRAINTS:\n{constraints_str}\n"
        f"{history_section}"
        "\nRequirements:\n"
        "1. Be factually accurate and consistent with ground truth\n"
        "2. Stay focused on the task\n"
        "3. Be consistent with prior conversation turns\n"
        "4. Follow the schema exactly if one is provided\n\n"
        'Return JSON with this schema:\n'
        '{"output": "<your generated response>"}\n\n'
        "Return ONLY the JSON response."
    )

    system = (
        "You are a reliable AI assistant that generates accurate, on-task responses. "
        "You must follow all provided constraints exactly. Respond only in valid JSON."
    )

    result = await call_llm(prompt, system=system)
    if result is None:
        return None, model

    corrected = result.get("output")
    if corrected is None:
        corrected = result.get("corrected_output")
    if corrected is None:
        # Try to extract any reasonable output from the response
        corrected = result.get("response")

    # Try to parse if it looks like JSON
    if isinstance(corrected, str):
        try:
            corrected = json.loads(corrected)
        except (json.JSONDecodeError, TypeError):
            pass

    return corrected, model


async def _layer3_full_reprompt(
    output: Any,
    task: Optional[str],
    checks: Dict[str, CheckResult],
    schema: Optional[Dict[str, Any]],
    ground_truth: Any,
    conversation_history: Optional[List[ConversationTurn]],
    input_data: Any,
) -> tuple:
    """Layer 3: Full re-prompt with explicit failure feedback."""
    model = _get_strong_model()

    output_str = output if isinstance(output, str) else json.dumps(output, default=str)
    failures = format_check_failures(checks)

    constraints: List[str] = []
    if schema:
        constraints.append(f"Schema: {json.dumps(schema)}")
    if ground_truth:
        truth_str = ground_truth if isinstance(ground_truth, str) else json.dumps(ground_truth, default=str)
        constraints.append(f"Ground truth: {truth_str}")

    constraints_str = "\n".join(f"- {c}" for c in constraints) if constraints else "None specified."

    history_section = ""
    if conversation_history:
        history_str = format_history(conversation_history)
        history_section = f"\nConversation history:\n{history_str}\n"

    input_section = ""
    if input_data is not None:
        input_str = input_data if isinstance(input_data, str) else json.dumps(input_data, default=str)
        input_section = f"\nINPUT CONTEXT:\n{input_str}\n"

    prompt = (
        "You are a reliable AI assistant. A previous response to this task "
        "FAILED verification. Generate a corrected response.\n\n"
        f"TASK: {task or 'Not specified'}\n"
        f"{input_section}"
        f"\nWHAT WENT WRONG:\n{failures}\n"
        f"\nCONSTRAINTS:\n{constraints_str}\n"
        f"{history_section}"
        "\nCRITICAL: The previous response failed because of the issues above. "
        "Your response MUST avoid these specific problems. Be conservative "
        "and precise. When uncertain, acknowledge uncertainty rather than "
        "fabricate.\n\n"
        'Return JSON with this schema:\n'
        '{"output": "<your corrected response>"}\n\n'
        "Return ONLY the JSON response."
    )

    system = (
        "You are a reliable AI assistant that must avoid the specific failures "
        "described. Be conservative and precise. Respond only in valid JSON."
    )

    result = await call_llm(prompt, system=system)
    if result is None:
        return None, model

    corrected = result.get("output")
    if corrected is None:
        corrected = result.get("corrected_output")
    if corrected is None:
        corrected = result.get("response")

    if isinstance(corrected, str):
        try:
            corrected = json.loads(corrected)
        except (json.JSONDecodeError, TypeError):
            pass

    return corrected, model
```

### Step 4: Run tests to verify they pass

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && python3 -m pytest services/verification-engine/tests/test_correction.py -v`
Expected: 12 PASSED

### Step 5: Run ALL engine tests

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && python3 -m pytest services/verification-engine/tests/ -v`
Expected: All pass (existing 49 + 4 from T2 + 12 from T3 = 65)

### Step 6: Commit

```bash
git add services/verification-engine/engine/correction.py services/verification-engine/tests/test_correction.py
git commit -m "feat(engine): add correction cascade module with select_layer and 3-layer correction"
```

---

## Task 4: Shared Models — VerifyResponse Update

**Files:**
- Modify: `services/shared/shared/models.py`
- Modify: `services/shared/tests/test_models.py`

### Step 1: Write the failing tests

Append to `services/shared/tests/test_models.py`:

```python
# --- Correction response model tests ---


def test_correction_attempt_response_creation():
    from shared.models import CorrectionAttemptResponse
    attempt = CorrectionAttemptResponse(
        layer=1,
        layer_name="repair",
        corrected_output="fixed",
        confidence=0.9,
        action="pass",
        success=True,
        latency_ms=340.0,
    )
    assert attempt.layer == 1
    assert attempt.success is True


def test_verify_response_with_correction_fields():
    from shared.models import VerifyResponse, CorrectionAttemptResponse
    response = VerifyResponse(
        execution_id="exec-123",
        confidence=0.9,
        action="pass",
        output="corrected output",
        corrected=True,
        original_output="bad output",
        correction_attempts=[
            CorrectionAttemptResponse(
                layer=1, layer_name="repair", corrected_output="fixed",
                confidence=0.9, action="pass", success=True, latency_ms=340.0,
            ),
        ],
    )
    assert response.corrected is True
    assert response.original_output == "bad output"
    assert len(response.correction_attempts) == 1


def test_verify_response_backward_compat_no_correction():
    from shared.models import VerifyResponse
    response = VerifyResponse(
        execution_id="exec-456",
        confidence=0.8,
        action="pass",
        output="output",
    )
    assert response.corrected is False
    assert response.original_output is None
    assert response.correction_attempts is None
```

### Step 2: Run tests to verify they fail

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && PYTHONPATH=services/shared python3 -m pytest services/shared/tests/test_models.py -v -k "correction"`
Expected: FAIL — `ImportError: cannot import name 'CorrectionAttemptResponse'`

### Step 3: Implement the model changes

Add to `services/shared/shared/models.py` — before `VerifyResponse`:

```python
class CorrectionAttemptResponse(BaseModel):
    """Wire format for a single correction attempt."""

    layer: int
    layer_name: str
    corrected_output: Any = None
    confidence: Optional[float] = None
    action: str = "pass"
    success: bool = False
    latency_ms: float = 0.0
```

Update `VerifyResponse` — add new fields after `checks`:

```python
class VerifyResponse(BaseModel):
    """Response from synchronous verification."""

    execution_id: str
    confidence: Optional[float] = None
    action: str = "pass"
    output: Any = None
    corrections: Optional[List[Dict[str, Any]]] = None
    checks: Dict[str, CheckResult] = Field(default_factory=dict)
    corrected: bool = False
    original_output: Optional[Any] = None
    correction_attempts: Optional[List[CorrectionAttemptResponse]] = None
```

**IMPORTANT:** Also update the root-level `services/shared/models.py` to keep it in sync (it shadows `services/shared/shared/models.py` — see memory notes about stale file issue).

### Step 4: Run tests to verify they pass

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && PYTHONPATH=services/shared python3 -m pytest services/shared/tests/test_models.py -v`
Expected: All pass (existing 22 + 3 new = 25)

### Step 5: Commit

```bash
git add services/shared/shared/models.py services/shared/models.py services/shared/tests/test_models.py
git commit -m "feat(shared): add CorrectionAttemptResponse and correction fields to VerifyResponse"
```

---

## Task 5: Gateway Orchestration — Correction Loop

**Files:**
- Modify: `services/sync-gateway/app/routes.py`
- Modify: `services/sync-gateway/tests/test_routes.py`

### Step 1: Write the failing tests

Append to `services/sync-gateway/tests/test_routes.py`:

```python
# --- Correction cascade tests ---


@pytest.mark.asyncio
async def test_verify_no_correction_unchanged(client, mock_redis):
    """When correction=none (default), behavior is identical to before."""
    mock_result = VerificationResult(
        confidence=0.4,
        action="block",
        checks={
            "schema": CheckResult(check_type="schema", score=0.0, passed=False),
        },
    )

    with patch("app.routes.run_verification", new_callable=AsyncMock, return_value=mock_result):
        response = await client.post(
            "/v1/verify",
            json={
                "agent_id": "test-bot",
                "input": "hello",
                "output": "world",
                "metadata": {"correction": "none"},
            },
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "block"
    assert data["corrected"] is False


@pytest.mark.asyncio
async def test_verify_correction_layer1_succeeds(client, mock_redis):
    """Correction cascade: Layer 1 succeeds → returns corrected output."""
    from engine.models import CorrectionAttempt

    # Initial verification fails
    failed_result = VerificationResult(
        confidence=0.6,
        action="flag",
        checks={
            "schema": CheckResult(check_type="schema", score=0.0, passed=False,
                                  details={"errors": ["missing field"]}),
            "hallucination": CheckResult(check_type="hallucination", score=1.0, passed=True),
            "drift": CheckResult(check_type="drift", score=0.9, passed=True),
        },
    )
    # Re-verification passes
    pass_result = VerificationResult(
        confidence=0.95,
        action="pass",
        checks={
            "schema": CheckResult(check_type="schema", score=1.0, passed=True),
            "hallucination": CheckResult(check_type="hallucination", score=1.0, passed=True),
            "drift": CheckResult(check_type="drift", score=0.9, passed=True),
        },
    )
    mock_correction = CorrectionAttempt(
        layer=1, layer_name="repair", input_action="flag",
        input_confidence=0.6, corrected_output='{"revenue": 5200000}',
        model_used="gpt-4o-mini", latency_ms=300.0, success=True,
    )

    with patch("app.routes.run_verification", new_callable=AsyncMock, side_effect=[failed_result, pass_result]), \
         patch("app.routes.run_correction", new_callable=AsyncMock, return_value=mock_correction):
        response = await client.post(
            "/v1/verify",
            json={
                "agent_id": "test-bot",
                "input": "hello",
                "output": '{"revnue": 5200000}',
                "metadata": {"correction": "cascade"},
            },
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "pass"
    assert data["corrected"] is True
    assert data["confidence"] == 0.95


@pytest.mark.asyncio
async def test_verify_correction_escalates_l1_to_l2(client, mock_redis):
    """Layer 1 fails, Layer 2 succeeds → 2 attempts, corrected."""
    from engine.models import CorrectionAttempt

    failed_result = VerificationResult(confidence=0.55, action="flag", checks={
        "schema": CheckResult(check_type="schema", score=0.0, passed=False),
        "hallucination": CheckResult(check_type="hallucination", score=1.0, passed=True),
    })
    still_failed = VerificationResult(confidence=0.45, action="block", checks={
        "schema": CheckResult(check_type="schema", score=0.0, passed=False),
    })
    pass_result = VerificationResult(confidence=0.9, action="pass", checks={
        "schema": CheckResult(check_type="schema", score=1.0, passed=True),
    })

    l1_attempt = CorrectionAttempt(
        layer=1, layer_name="repair", input_action="flag",
        corrected_output="still broken", model_used="gpt-4o-mini",
        latency_ms=200.0, success=True,
    )
    l2_attempt = CorrectionAttempt(
        layer=2, layer_name="constrained_regen", input_action="block",
        corrected_output="properly fixed", model_used="gpt-4o",
        latency_ms=1200.0, success=True,
    )

    # verify called 3 times: initial, after L1, after L2
    with patch("app.routes.run_verification", new_callable=AsyncMock,
               side_effect=[failed_result, still_failed, pass_result]), \
         patch("app.routes.run_correction", new_callable=AsyncMock,
               side_effect=[l1_attempt, l2_attempt]):
        response = await client.post(
            "/v1/verify",
            json={
                "agent_id": "test-bot",
                "input": "hello",
                "output": "broken",
                "metadata": {"correction": "cascade"},
            },
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "pass"
    assert data["corrected"] is True


@pytest.mark.asyncio
async def test_verify_correction_all_fail_blocks(client, mock_redis):
    """All correction layers fail → block."""
    from engine.models import CorrectionAttempt

    failed = VerificationResult(confidence=0.4, action="block", checks={
        "hallucination": CheckResult(check_type="hallucination", score=0.1, passed=False),
    })
    still_failed = VerificationResult(confidence=0.35, action="block", checks={
        "hallucination": CheckResult(check_type="hallucination", score=0.2, passed=False),
    })

    attempt = CorrectionAttempt(
        layer=2, layer_name="constrained_regen", input_action="block",
        corrected_output="still bad", model_used="gpt-4o",
        latency_ms=1000.0, success=True,
    )

    with patch("app.routes.run_verification", new_callable=AsyncMock,
               side_effect=[failed, still_failed, still_failed]), \
         patch("app.routes.run_correction", new_callable=AsyncMock, return_value=attempt):
        response = await client.post(
            "/v1/verify",
            json={
                "agent_id": "test-bot",
                "input": "hello",
                "output": "bad output",
                "metadata": {"correction": "cascade"},
            },
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "block"
    assert data["corrected"] is False


@pytest.mark.asyncio
async def test_verify_correction_timeout_passthrough(client, mock_redis):
    """10s timeout during correction → pass-through."""
    async def slow_verify(**kwargs):
        await asyncio.sleep(15)

    with patch("app.routes.run_verification", side_effect=slow_verify):
        response = await client.post(
            "/v1/verify",
            json={
                "agent_id": "test-bot",
                "input": "hello",
                "output": "world",
                "metadata": {"correction": "cascade"},
            },
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "pass"
    assert data["corrected"] is False


@pytest.mark.asyncio
async def test_verify_correction_uses_original_output(client, mock_redis):
    """Correction always uses original output, not previous correction's output."""
    from engine.models import CorrectionAttempt

    original_output = "original broken output"

    failed = VerificationResult(confidence=0.4, action="block", checks={})
    still_failed = VerificationResult(confidence=0.4, action="block", checks={})
    pass_result = VerificationResult(confidence=0.9, action="pass", checks={})

    correction_calls = []

    async def mock_correct(**kwargs):
        correction_calls.append(kwargs.get("output"))
        return CorrectionAttempt(
            layer=kwargs.get("layer", 2), layer_name="constrained_regen",
            input_action="block", corrected_output="corrected v" + str(len(correction_calls)),
            model_used="gpt-4o", latency_ms=500.0, success=True,
        )

    with patch("app.routes.run_verification", new_callable=AsyncMock,
               side_effect=[failed, still_failed, pass_result]), \
         patch("app.routes.run_correction", side_effect=mock_correct):
        response = await client.post(
            "/v1/verify",
            json={
                "agent_id": "test-bot",
                "input": "hello",
                "output": original_output,
                "metadata": {"correction": "cascade"},
            },
            headers={"X-AgentGuard-Key": "test-key"},
        )

    # Both correction calls should receive the ORIGINAL output
    assert all(c == original_output for c in correction_calls)


@pytest.mark.asyncio
async def test_verify_correction_emits_redis_with_correction_metadata(client, mock_redis):
    """Redis events should include correction metadata."""
    from engine.models import CorrectionAttempt

    failed = VerificationResult(confidence=0.6, action="flag", checks={
        "schema": CheckResult(check_type="schema", score=0.0, passed=False),
    })
    pass_result = VerificationResult(confidence=0.95, action="pass", checks={
        "schema": CheckResult(check_type="schema", score=1.0, passed=True),
    })

    attempt = CorrectionAttempt(
        layer=1, layer_name="repair", input_action="flag",
        corrected_output="fixed", model_used="gpt-4o-mini",
        latency_ms=300.0, success=True,
    )

    with patch("app.routes.run_verification", new_callable=AsyncMock,
               side_effect=[failed, pass_result]), \
         patch("app.routes.run_correction", new_callable=AsyncMock, return_value=attempt):
        response = await client.post(
            "/v1/verify",
            json={
                "agent_id": "test-bot",
                "input": "hello",
                "output": "broken",
                "metadata": {"correction": "cascade"},
            },
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert response.status_code == 200
    # Check Redis was called with correction data
    assert mock_redis.xadd.call_count >= 2
    verified_call = None
    for call in mock_redis.xadd.call_args_list:
        if call[0][0] == "executions.verified":
            verified_call = call
            break
    assert verified_call is not None
    data_str = verified_call[0][1]["data"]
    verified_data = json.loads(data_str)
    assert verified_data["corrected"] == "True"


@pytest.mark.asyncio
async def test_verify_pass_skips_correction(client, mock_redis):
    """When initial verification passes, correction is NOT triggered."""
    pass_result = VerificationResult(
        confidence=0.95, action="pass", checks={
            "schema": CheckResult(check_type="schema", score=1.0, passed=True),
        },
    )

    with patch("app.routes.run_verification", new_callable=AsyncMock, return_value=pass_result) as mock_verify:
        response = await client.post(
            "/v1/verify",
            json={
                "agent_id": "test-bot",
                "input": "hello",
                "output": "good output",
                "metadata": {"correction": "cascade"},
            },
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "pass"
    assert data["corrected"] is False
    # verify called only once (no re-verification needed)
    assert mock_verify.call_count == 1
```

### Step 2: Run tests to verify they fail

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && PYTHONPATH=services/shared:services/verification-engine python3 -m pytest services/sync-gateway/tests/test_routes.py -v -k "correction"`
Expected: FAIL — `AttributeError: module 'app.routes' has no attribute 'run_correction'`

### Step 3: Implement the gateway changes

Update `services/sync-gateway/app/routes.py`:

Key changes:
1. Add `CORRECTION_TIMEOUT_S = 10.0`
2. Import correction functions: `from engine.correction import correct as run_correction, select_layer`
3. Extract `correction_mode` and `transparency` from metadata
4. Dynamic timeout based on correction mode
5. Add correction orchestration logic after initial verification
6. Build response with correction fields
7. Include correction data in Redis events

The full implementation is specified in the design doc Section 5. The gateway's `verify_endpoint` becomes the orchestrator — it calls `run_verification` first, and if the result is not pass AND correction mode is "cascade", it enters the correction loop.

**Critical implementation detail:** `run_correction` is imported at module level from `engine.correction` as `from engine.correction import correct as run_correction, select_layer`. Tests will patch `app.routes.run_correction` and `app.routes.run_verification`.

### Step 4: Run tests to verify they pass

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && PYTHONPATH=services/shared:services/verification-engine python3 -m pytest services/sync-gateway/tests/test_routes.py -v`
Expected: All pass (existing 7 + 8 new = 15)

### Step 5: Commit

```bash
git add services/sync-gateway/app/routes.py services/sync-gateway/tests/test_routes.py
git commit -m "feat(gateway): add correction cascade orchestration with 10s timeout and Redis metadata"
```

---

## Task 6: Storage Worker — Persist Corrected Flag

**Files:**
- Modify: `services/storage-worker/app/worker.py`
- Modify: `services/storage-worker/tests/test_worker.py`

### Step 1: Write the failing tests

Append to `services/storage-worker/tests/test_worker.py`:

```python
# --- Correction persistence tests ---


def test_process_verified_event_with_correction(mock_db_session):
    """process_verified_event should persist corrected=True and correction metadata."""
    event = {
        "execution_id": "exec-corrected",
        "agent_id": "test-bot",
        "confidence": "0.9",
        "action": "pass",
        "checks": json.dumps({
            "schema": {"check_type": "schema", "score": 1.0, "passed": True, "details": {}},
        }),
        "corrected": "True",
        "correction_attempts": json.dumps([
            {"layer": 1, "layer_name": "repair", "success": True, "latency_ms": 340.0},
        ]),
    }
    result = process_verified_event(event, mock_db_session)
    assert result["corrected"] is True

    # The UPDATE call should include corrected=True
    update_call = mock_db_session.execute.call_args_list[-1]
    params = update_call[0][1]
    assert params["corrected"] is True


def test_process_verified_event_without_correction(mock_db_session):
    """process_verified_event without correction data → corrected=False."""
    event = {
        "execution_id": "exec-no-correct",
        "agent_id": "test-bot",
        "confidence": "0.8",
        "action": "pass",
        "checks": "{}",
    }
    result = process_verified_event(event, mock_db_session)
    assert result["corrected"] is False

    update_call = mock_db_session.execute.call_args_list[-1]
    params = update_call[0][1]
    assert params["corrected"] is False


def test_process_verified_event_preserves_correction_metadata(mock_db_session):
    """Correction attempts should be stored in metadata."""
    event = {
        "execution_id": "exec-meta",
        "agent_id": "test-bot",
        "confidence": "0.85",
        "action": "pass",
        "checks": "{}",
        "corrected": "True",
        "correction_attempts": json.dumps([
            {"layer": 1, "layer_name": "repair", "success": False},
            {"layer": 2, "layer_name": "constrained_regen", "success": True},
        ]),
        "original_output": json.dumps("bad output"),
    }
    result = process_verified_event(event, mock_db_session)
    assert result["corrected"] is True
```

### Step 2: Run tests to verify they fail

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && PYTHONPATH=services/shared python3 -m pytest services/storage-worker/tests/test_worker.py -v -k "correction"`
Expected: FAIL — assertion errors on `corrected` key

### Step 3: Implement the storage worker changes

Update `services/storage-worker/app/worker.py` `process_verified_event`:

1. Extract `corrected` from event_data (parse "True"/"False" string to bool)
2. Extract `correction_attempts` and `original_output` for metadata
3. Update the SQL UPDATE to include `corrected` column and `metadata`
4. Return `corrected` in the result dict

### Step 4: Run tests

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && PYTHONPATH=services/shared python3 -m pytest services/storage-worker/tests/test_worker.py -v`
Expected: All pass (existing 12 + 3 new = 15)

### Step 5: Commit

```bash
git add services/storage-worker/app/worker.py services/storage-worker/tests/test_worker.py
git commit -m "feat(storage): persist corrected flag and correction metadata from verified events"
```

---

## Task 7: SDK Transport — Dual Timeout & Forwarding

**Files:**
- Modify: `sdk/python/agentguard/transport.py`
- Modify: `sdk/python/tests/test_transport.py`

### Step 1: Write the failing tests

Append to `sdk/python/tests/test_transport.py`:

```python
# --- SyncTransport correction tests ---


@respx.mock
def test_sync_transport_verify_forwards_correction_metadata():
    """verify() should include correction and transparency in metadata."""
    import json as _json
    route = respx.post("https://api.agentguard.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "exec-123", "confidence": 0.9, "action": "pass",
            "output": "corrected", "checks": {}, "corrected": True,
        })
    )
    transport = SyncTransport(
        api_url="https://api.agentguard.dev",
        api_key="ag_test_key",
    )
    event = ExecutionEvent(agent_id="test", input={}, output={})
    transport.verify(event, correction="cascade", transparency="transparent")

    body = _json.loads(route.calls.last.request.content)
    assert body["metadata"]["correction"] == "cascade"
    assert body["metadata"]["transparency"] == "transparent"
    transport.close()


@respx.mock
def test_sync_transport_correction_client_uses_longer_timeout():
    """When correction=cascade, should use correction timeout client (12s)."""
    route = respx.post("https://api.agentguard.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "e", "confidence": 0.9, "action": "pass",
            "output": "ok", "checks": {},
        })
    )
    transport = SyncTransport(
        api_url="https://api.agentguard.dev",
        api_key="ag_test_key",
        timeout_s=2.0,
        correction_timeout_s=12.0,
    )
    event = ExecutionEvent(agent_id="test", input={}, output={})
    transport.verify(event, correction="cascade")

    # Verify the correction client was used (has 12s timeout)
    assert transport._correction_client is not None
    assert transport._correction_client.timeout.connect == 12.0
    transport.close()


@respx.mock
def test_sync_transport_default_client_for_no_correction():
    """When correction=none, should use default client (2s timeout)."""
    route = respx.post("https://api.agentguard.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "e", "confidence": 0.9, "action": "pass",
            "output": "ok", "checks": {},
        })
    )
    transport = SyncTransport(
        api_url="https://api.agentguard.dev",
        api_key="ag_test_key",
        timeout_s=2.0,
        correction_timeout_s=12.0,
    )
    event = ExecutionEvent(agent_id="test", input={}, output={})
    transport.verify(event, correction="none")

    # Correction client should NOT have been created
    assert transport._correction_client is None
    transport.close()


@respx.mock
def test_sync_transport_close_closes_both_clients():
    """close() should close both default and correction clients."""
    respx.post("https://api.agentguard.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "e", "confidence": 0.9, "action": "pass",
            "output": "ok", "checks": {},
        })
    )
    transport = SyncTransport(
        api_url="https://api.agentguard.dev",
        api_key="ag_test_key",
    )
    event = ExecutionEvent(agent_id="test", input={}, output={})
    # Trigger correction client creation
    transport.verify(event, correction="cascade")
    assert transport._correction_client is not None

    transport.close()
    assert transport._client.is_closed
    assert transport._correction_client.is_closed
```

### Step 2: Run tests to verify they fail

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && python3 -m pytest sdk/python/tests/test_transport.py -v -k "correction or both_clients"`
Expected: FAIL — `TypeError: verify() got unexpected keyword argument 'correction'`

### Step 3: Implement the transport changes

Update `sdk/python/agentguard/transport.py` `SyncTransport`:

1. Add `correction_timeout_s: float = 12.0` parameter to `__init__`
2. Add `self._correction_client: Optional[httpx.Client] = None` field
3. Add `_get_correction_client()` method (lazy init)
4. Update `verify()` signature: add `correction: str = "none"`, `transparency: str = "opaque"` params
5. Select client based on correction mode
6. Add correction and transparency to metadata in payload
7. Update `close()` to also close correction client

### Step 4: Run tests

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && python3 -m pytest sdk/python/tests/test_transport.py -v`
Expected: All pass (existing 8 + 4 new = 12)

### Step 5: Commit

```bash
git add sdk/python/agentguard/transport.py sdk/python/tests/test_transport.py
git commit -m "feat(sdk): add dual-timeout SyncTransport with correction/transparency forwarding"
```

---

## Task 8: SDK Models + Guard Client

**Files:**
- Modify: `sdk/python/agentguard/models.py`
- Modify: `sdk/python/agentguard/guard.py`
- Modify: `sdk/python/tests/test_guard.py`
- Modify: `sdk/python/tests/test_models.py`

### Step 1: Write the failing tests

Append to `sdk/python/tests/test_models.py`:

```python
# --- Correction fields on GuardResult ---


def test_guard_result_with_correction_fields():
    from agentguard.models import GuardResult
    result = GuardResult(
        output="corrected output",
        confidence=0.9,
        action="pass",
        execution_id="exec-123",
        corrected=True,
        original_output="bad output",
        corrections=[{"layer": 1, "success": True}],
    )
    assert result.corrected is True
    assert result.original_output == "bad output"


def test_guard_result_backward_compat():
    from agentguard.models import GuardResult
    result = GuardResult(
        output="output",
        execution_id="exec-456",
    )
    assert result.corrected is False
    assert result.original_output is None
```

Append to `sdk/python/tests/test_guard.py`:

```python
# --- Correction integration tests ---


@respx.mock
def test_guard_sync_correction_returns_corrected_output():
    """When server returns corrected=True, GuardResult should reflect corrected output."""
    respx.post("https://api.agentguard.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "exec-corrected",
            "confidence": 0.9,
            "action": "pass",
            "output": "corrected answer",
            "checks": {},
            "corrected": True,
            "original_output": "bad answer",
            "correction_attempts": [
                {"layer": 1, "layer_name": "repair", "success": True, "latency_ms": 300},
            ],
        })
    )

    guard = AgentGuard(
        api_key="ag_test_key",
        config=GuardConfig(
            mode="sync",
            api_url="https://api.agentguard.dev",
            correction="cascade",
        ),
    )

    @guard.watch(agent_id="bot", task="task")
    def my_agent(q: str) -> str:
        return "bad answer"

    result = my_agent("test")
    assert result.output == "corrected answer"
    assert result.corrected is True
    assert result.action == "pass"
    guard.close()


@respx.mock
def test_guard_sync_correction_opaque_hides_details():
    """Opaque mode: original_output and corrections should be None."""
    respx.post("https://api.agentguard.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "exec-opaque",
            "confidence": 0.9,
            "action": "pass",
            "output": "corrected",
            "checks": {},
            "corrected": True,
            "original_output": None,
            "correction_attempts": None,
        })
    )

    guard = AgentGuard(
        api_key="ag_test_key",
        config=GuardConfig(
            mode="sync",
            api_url="https://api.agentguard.dev",
            correction="cascade",
            transparency="opaque",
        ),
    )

    @guard.watch(agent_id="bot", task="task")
    def my_agent(q: str) -> str:
        return "bad"

    result = my_agent("test")
    assert result.corrected is True
    assert result.original_output is None
    assert result.corrections is None
    guard.close()


@respx.mock
def test_guard_sync_correction_transparent_shows_details():
    """Transparent mode: original_output and corrections should be populated."""
    respx.post("https://api.agentguard.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "exec-transparent",
            "confidence": 0.9,
            "action": "pass",
            "output": "corrected",
            "checks": {},
            "corrected": True,
            "original_output": "bad output",
            "correction_attempts": [
                {"layer": 1, "layer_name": "repair", "success": True},
            ],
        })
    )

    guard = AgentGuard(
        api_key="ag_test_key",
        config=GuardConfig(
            mode="sync",
            api_url="https://api.agentguard.dev",
            correction="cascade",
            transparency="transparent",
        ),
    )

    @guard.watch(agent_id="bot", task="task")
    def my_agent(q: str) -> str:
        return "bad"

    result = my_agent("test")
    assert result.corrected is True
    assert result.original_output == "bad output"
    assert result.corrections is not None
    assert len(result.corrections) == 1
    guard.close()


@respx.mock
def test_guard_sync_correction_failed_raises_block():
    """When correction fails (all attempts exhausted), should raise AgentGuardBlockError."""
    respx.post("https://api.agentguard.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "exec-block",
            "confidence": 0.2,
            "action": "block",
            "output": "bad output",
            "checks": {},
            "corrected": False,
        })
    )

    guard = AgentGuard(
        api_key="ag_test_key",
        config=GuardConfig(
            mode="sync",
            api_url="https://api.agentguard.dev",
            correction="cascade",
        ),
    )

    @guard.watch(agent_id="bot", task="task")
    def my_agent(q: str) -> str:
        return "bad"

    with pytest.raises(AgentGuardBlockError):
        my_agent("test")
    guard.close()


@respx.mock
def test_guard_async_mode_ignores_correction():
    """Async mode should ignore correction setting — fire-and-forget."""
    respx.post("https://api.agentguard.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 1})
    )

    guard = AgentGuard(
        api_key="ag_test_key",
        config=GuardConfig(
            mode="async",
            api_url="https://api.agentguard.dev",
            correction="cascade",  # should be ignored
        ),
    )

    @guard.watch(agent_id="bot", task="task")
    def my_agent(q: str) -> str:
        return "answer"

    result = my_agent("test")
    assert result.action == "pass"  # always pass in async mode
    assert result.corrected is False
    guard.close()


@respx.mock
def test_guard_sync_no_correction_unchanged():
    """correction=none → existing behavior, no correction fields."""
    respx.post("https://api.agentguard.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "exec-none",
            "confidence": 0.6,
            "action": "flag",
            "output": "flagged",
            "checks": {},
        })
    )

    guard = AgentGuard(
        api_key="ag_test_key",
        config=GuardConfig(
            mode="sync",
            api_url="https://api.agentguard.dev",
            correction="none",
        ),
    )

    @guard.watch(agent_id="bot", task="task")
    def my_agent(q: str) -> str:
        return "answer"

    result = my_agent("test")
    assert result.action == "flag"
    assert result.corrected is False
    guard.close()
```

### Step 2: Run tests to verify they fail

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && python3 -m pytest sdk/python/tests/test_models.py sdk/python/tests/test_guard.py -v -k "correction or backward_compat_guard or opaque or transparent or async_mode_ignores"`
Expected: FAIL — various assertion errors

### Step 3: Implement the changes

**sdk/python/agentguard/models.py** — Add to `GuardResult`:

```python
class GuardResult(BaseModel):
    output: Any
    confidence: Optional[float] = None
    action: str = "pass"
    corrections: Optional[List[Dict[str, Any]]] = None
    execution_id: str
    verification: Optional[Dict[str, Any]] = None
    corrected: bool = False
    original_output: Optional[Any] = None
```

**sdk/python/agentguard/guard.py** — Update `_process_event`:

1. Pass `correction=self.config.correction` and `transparency=self.config.transparency` to `self._sync_transport.verify()`
2. Extract `corrected` from response
3. When `corrected=True`, use `response.get("output", event.output)` as output
4. Map `original_output` and `correction_attempts` to GuardResult fields
5. Pass `correction_timeout_s=12.0` when constructing `SyncTransport` if correction enabled

### Step 4: Run ALL SDK tests

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && python3 -m pytest sdk/python/tests/ -v`
Expected: All pass (existing 60 + 2 model + 6 guard = 68)

### Step 5: Commit

```bash
git add sdk/python/agentguard/models.py sdk/python/agentguard/guard.py sdk/python/tests/test_models.py sdk/python/tests/test_guard.py
git commit -m "feat(sdk): add correction support to GuardResult and _process_event with opaque/transparent modes"
```

---

## Task 9: Dashboard — Correction Visibility

**Files:**
- Modify: Trace detail page (add CorrectionTimeline)
- Create: CorrectionTimeline component
- Create: OutputDiff component
- Modify: Fleet health (add correction rate)
- Modify: Failures page (add corrected column/filter)
- Modify: Agent detail (correction stats)
- Modify: i18n keys

### Step 1: Run typecheck as baseline

Run: `cd /Users/thakurg/Hive/Research/AgentGuard/nextjs-application && pnpm --filter web typecheck`
Expected: PASS

### Step 2: Add i18n keys

Update `nextjs-application/apps/web/public/locales/en/agentguard.json`:
- Add `correction.*` keys (timeline title, attempt labels, output diff title, etc.)
- Add `fleet.correctionRate`, `fleet.correctionRateHigh`, etc.
- Add `failures.corrected`, `failures.correctedFilter`

### Step 3: Create CorrectionTimeline component

Create `nextjs-application/apps/web/app/home/[account]/agents/[agentId]/traces/[executionId]/_components/correction-timeline.tsx`

Client component showing:
- Each attempt as a collapsible card (layer name, confidence, action, latency)
- Green checkmark on success, red X on failure
- Expandable section for corrected output

### Step 4: Create OutputDiff component

Create `nextjs-application/apps/web/app/home/[account]/agents/[agentId]/traces/[executionId]/_components/output-diff.tsx`

Client component showing inline text diff:
- Red lines for removed content (original)
- Green lines for added content (corrected)
- JSON pretty-printing for structured outputs

### Step 5: Update trace detail page

Modify the trace detail page to:
- Check if execution has `corrected=true` in metadata
- If so, render `CorrectionTimeline` and `OutputDiff` sections
- Parse correction_attempts from metadata JSON

### Step 6: Update fleet health charts

Add correction rate metric:
- Query: `COUNT(corrected=true) / COUNT(action IN ('flag','block') OR corrected=true)`
- Badge with color coding: >80% green, 50-80% amber, <50% red

### Step 7: Update failures page

- Add "Corrected" column to failures table
- Add "Corrected" filter (All, Corrected, Uncorrected)
- Update loader to join corrected column

### Step 8: Run typecheck

Run: `cd /Users/thakurg/Hive/Research/AgentGuard/nextjs-application && pnpm --filter web typecheck`
Expected: PASS

### Step 9: Commit

```bash
git add nextjs-application/apps/web/
git commit -m "feat(dashboard): add CorrectionTimeline, OutputDiff, correction rate, and corrected filter"
```

---

## Task 10: Integration Tests

**Files:**
- Create: `tests/integration/test_correction_path.py`

### Step 1: Write integration tests

```python
"""Integration tests for the correction cascade path.

Tests the full flow: SDK config → Gateway → Engine verify → Engine correct
→ re-verify → response with correction metadata → Redis events.
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Add service paths
_root = Path(__file__).resolve().parent.parent.parent
_gw_path = str(_root / "services" / "sync-gateway")
if _gw_path not in sys.path:
    sys.path.insert(0, _gw_path)

from engine.models import CheckResult, CorrectionAttempt, VerificationResult


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.xadd = AsyncMock()
    r.aclose = AsyncMock()
    return r


@pytest.fixture
def gateway_app(mock_redis):
    from app.main import create_app
    application = create_app()
    application.state.redis = mock_redis
    return application


@pytest_asyncio.fixture
async def client(gateway_app):
    transport = ASGITransport(app=gateway_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.integration
@pytest.mark.asyncio
async def test_correction_succeeds_layer1(client, mock_redis):
    """Full integration: verify fails → correct L1 → re-verify passes → corrected response."""
    failed = VerificationResult(confidence=0.6, action="flag", checks={
        "schema": CheckResult(check_type="schema", score=0.0, passed=False,
                              details={"errors": ["missing field"]}),
        "hallucination": CheckResult(check_type="hallucination", score=1.0, passed=True),
    })
    passed = VerificationResult(confidence=0.95, action="pass", checks={
        "schema": CheckResult(check_type="schema", score=1.0, passed=True),
        "hallucination": CheckResult(check_type="hallucination", score=1.0, passed=True),
    })
    attempt = CorrectionAttempt(
        layer=1, layer_name="repair", input_action="flag", input_confidence=0.6,
        corrected_output='{"revenue": 5200000}',
        model_used="gpt-4o-mini", latency_ms=300.0, success=True,
    )

    with patch("app.routes.run_verification", new_callable=AsyncMock, side_effect=[failed, passed]), \
         patch("app.routes.run_correction", new_callable=AsyncMock, return_value=attempt):
        response = await client.post(
            "/v1/verify",
            json={
                "agent_id": "test-bot",
                "input": "query",
                "output": '{"revnue": 5200000}',
                "task": "Generate report",
                "metadata": {"correction": "cascade"},
            },
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "pass"
    assert data["corrected"] is True
    assert data["confidence"] == 0.95

    # Verify Redis events emitted
    assert mock_redis.xadd.call_count >= 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_correction_escalates_l1_l2(client, mock_redis):
    """L1 fails → L2 succeeds → corrected with 2 attempts."""
    failed = VerificationResult(confidence=0.55, action="flag", checks={
        "schema": CheckResult(check_type="schema", score=0.0, passed=False),
    })
    still_failed = VerificationResult(confidence=0.4, action="block", checks={
        "schema": CheckResult(check_type="schema", score=0.0, passed=False),
    })
    passed = VerificationResult(confidence=0.9, action="pass", checks={
        "schema": CheckResult(check_type="schema", score=1.0, passed=True),
    })
    l1 = CorrectionAttempt(layer=1, layer_name="repair", input_action="flag",
                           corrected_output="bad", model_used="gpt-4o-mini",
                           latency_ms=200.0, success=True)
    l2 = CorrectionAttempt(layer=2, layer_name="constrained_regen", input_action="block",
                           corrected_output="good", model_used="gpt-4o",
                           latency_ms=1200.0, success=True)

    with patch("app.routes.run_verification", new_callable=AsyncMock,
               side_effect=[failed, still_failed, passed]), \
         patch("app.routes.run_correction", new_callable=AsyncMock, side_effect=[l1, l2]):
        response = await client.post(
            "/v1/verify",
            json={"agent_id": "bot", "input": "q", "output": "bad",
                  "metadata": {"correction": "cascade"}},
            headers={"X-AgentGuard-Key": "test-key"},
        )

    data = response.json()
    assert data["action"] == "pass"
    assert data["corrected"] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_correction_fails_all_layers(client, mock_redis):
    """All correction attempts fail → block."""
    failed = VerificationResult(confidence=0.3, action="block", checks={
        "hallucination": CheckResult(check_type="hallucination", score=0.1, passed=False),
    })
    attempt = CorrectionAttempt(layer=2, layer_name="constrained_regen",
                                input_action="block", corrected_output="still bad",
                                model_used="gpt-4o", latency_ms=1000.0, success=True)

    with patch("app.routes.run_verification", new_callable=AsyncMock, return_value=failed), \
         patch("app.routes.run_correction", new_callable=AsyncMock, return_value=attempt):
        response = await client.post(
            "/v1/verify",
            json={"agent_id": "bot", "input": "q", "output": "bad",
                  "metadata": {"correction": "cascade"}},
            headers={"X-AgentGuard-Key": "test-key"},
        )

    data = response.json()
    assert data["action"] == "block"
    assert data["corrected"] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_correction_regression(client, mock_redis):
    """correction=none → identical to Phase 2 behavior."""
    result = VerificationResult(confidence=0.6, action="flag", checks={
        "hallucination": CheckResult(check_type="hallucination", score=0.6, passed=True),
    })

    with patch("app.routes.run_verification", new_callable=AsyncMock, return_value=result):
        response = await client.post(
            "/v1/verify",
            json={"agent_id": "bot", "input": "q", "output": "output",
                  "metadata": {"correction": "none"}},
            headers={"X-AgentGuard-Key": "test-key"},
        )

    data = response.json()
    assert data["action"] == "flag"
    assert data["corrected"] is False
```

### Step 2: Run integration tests

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && PYTHONPATH=services/shared:services/verification-engine python3 -m pytest tests/integration/test_correction_path.py -v -m integration`
Expected: 4 PASSED

### Step 3: Run ALL integration tests

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && PYTHONPATH=services/shared:services/verification-engine python3 -m pytest tests/integration/ -v -m integration`
Expected: All pass (existing 6 + 4 new = 10)

### Step 4: Commit

```bash
git add tests/integration/test_correction_path.py
git commit -m "test(integration): add correction cascade path tests (L1 success, L1→L2, all fail, regression)"
```

---

## Task 11: Live LLM Test — 3 Correction Scenarios

**Files:**
- Modify: `scripts/test_live_verification.py`

### Step 1: Add 3 new scenarios

Append to the existing `scenarios` list:

```python
# Scenario 8: Schema violation → L1 repair fixes
{
    "name": "Schema violation corrected (L1 Repair)",
    "output": '{"revnue": 5200000, "profit": 800000}',  # typo in "revenue"
    "task": "Generate financial summary",
    "schema": {"type": "object", "required": ["revenue", "profit"], "properties": {
        "revenue": {"type": "number"}, "profit": {"type": "number"},
    }},
    "ground_truth": {"revenue": 5200000, "profit": 800000},
    "correction": "cascade",
    "expect_action": ["pass"],  # should be corrected
    "expect_corrected": True,
}

# Scenario 9: Hallucination → L2 regenerates with ground truth
{
    "name": "Hallucination corrected (L2 Constrained Regen)",
    "output": "Revenue was $999 trillion in Q3, a record-breaking quarter.",
    "task": "Summarize Q3 earnings",
    "ground_truth": {"revenue": "$5.2B", "quarter": "Q3 2025"},
    "correction": "cascade",
    "expect_action": ["pass", "flag"],
    "expect_corrected": True,
}

# Scenario 10: Uncorrectable output → all layers fail → block
{
    "name": "Uncorrectable output (all layers fail → block)",
    "output": "Let me tell you about my favorite pizza recipe instead of answering your question.",
    "task": "Provide Q3 financial analysis with revenue and profit figures",
    "schema": {"type": "object", "required": ["revenue", "profit", "analysis"]},
    "ground_truth": {"revenue": "$5.2B", "profit": "$800M"},
    "correction": "cascade",
    "expect_action": ["block"],
    "expect_corrected": False,
}
```

The live test runner needs to be updated to:
1. Import `correct` and `select_layer` from engine
2. Run the correction cascade loop for scenarios with `"correction": "cascade"`
3. Print correction attempt details (layer, latency, success)
4. Verify `expect_corrected` matches

### Step 2: Run live test

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && LITELLM_API_URL=... VERIFICATION_MODEL=openai/gpt-5.2 VERIFICATION_TIMEOUT_S=30 python3 scripts/test_live_verification.py`
Expected: All 10 scenarios pass

### Step 3: Commit

```bash
git add scripts/test_live_verification.py
git commit -m "test(live): add 3 correction cascade scenarios (L1 repair, L2 regen, uncorrectable)"
```

---

## Verification Checklist

After all tasks are complete, run the full test suite:

```bash
# Engine (65 tests)
cd /Users/thakurg/Hive/Research/AgentGuard && python3 -m pytest services/verification-engine/tests/ -v

# Gateway (15 tests)
PYTHONPATH=services/shared:services/verification-engine python3 -m pytest services/sync-gateway/tests/ -v

# Async worker (5 tests — unchanged)
PYTHONPATH=services/shared:services/verification-engine python3 -m pytest services/async-worker/tests/ -v

# Alert service (9 tests — unchanged)
PYTHONPATH=services/shared python3 -m pytest services/alert-service/tests/ -v

# Storage worker (15 tests)
PYTHONPATH=services/shared python3 -m pytest services/storage-worker/tests/ -v

# Shared models (25 tests)
PYTHONPATH=services/shared python3 -m pytest services/shared/tests/ -v

# SDK (68 tests)
python3 -m pytest sdk/python/tests/ -v

# Integration (10 tests)
PYTHONPATH=services/shared:services/verification-engine python3 -m pytest tests/integration/ -v -m integration

# Dashboard typecheck
cd nextjs-application && pnpm --filter web typecheck
```

**Expected total: ~212 tests passing + dashboard typecheck clean.**
