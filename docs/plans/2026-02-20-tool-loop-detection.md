# Tool Loop / Cycle Detection — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a 5th verification check that detects when an agent is stuck in a tool call loop, calling the same tool(s) repeatedly or excessively.

**Architecture:** New `engine/tool_loop.py` module following the same pattern as `schema_validator.py` (deterministic, no LLM). Analyzes the `steps` list from `IngestEvent` for three signals: total tool call count exceeding a threshold, consecutive repeated identical tool calls, and cyclic patterns. Integrated into the pipeline as an optional check that only runs when `steps` are provided. The pipeline signature gains an optional `steps` parameter, and both the async-worker and sync-gateway pass `event.steps` through.

**Tech Stack:** Python, Pydantic, pytest. No new dependencies.

---

### Task 1: Create the tool_loop check module with tests

**Files:**
- Create: `services/verification-engine/engine/tool_loop.py`
- Create: `services/verification-engine/tests/test_tool_loop.py`

**Step 1: Write the failing tests**

File: `services/verification-engine/tests/test_tool_loop.py`

```python
"""Tests for the tool loop / cycle detection check."""

from engine.tool_loop import check
from shared.models import StepRecord


def test_no_steps_skips():
    """No steps provided — check skipped, returns passed."""
    result = check(steps=[])
    assert result.check_type == "tool_loop"
    assert result.score == 1.0
    assert result.passed is True
    assert result.details.get("skipped") is True


def test_few_unique_steps_passes():
    """A handful of unique tool calls — no loop detected."""
    steps = [
        StepRecord(step_type="tool_call", name="search", input="q1", output="r1"),
        StepRecord(step_type="tool_call", name="read_file", input="f1", output="r2"),
        StepRecord(step_type="tool_call", name="write_file", input="f2", output="r3"),
    ]
    result = check(steps=steps)
    assert result.passed is True
    assert result.score == 1.0


def test_non_tool_steps_ignored():
    """LLM steps should not count toward tool loop detection."""
    steps = [
        StepRecord(step_type="llm", name="gpt-4", input="prompt", output="response"),
    ] * 30
    result = check(steps=steps)
    assert result.passed is True
    assert result.score == 1.0


def test_excessive_tool_calls_detected():
    """More than max_tool_calls unique tool calls triggers detection."""
    steps = [
        StepRecord(step_type="tool_call", name=f"tool_{i}", input=f"in_{i}", output=f"out_{i}")
        for i in range(30)
    ]
    result = check(steps=steps, max_tool_calls=20)
    assert result.passed is False
    assert result.score < 1.0
    assert "excessive_count" in result.details


def test_consecutive_repeats_detected():
    """Same tool called N times in a row triggers detection."""
    steps = [
        StepRecord(step_type="tool_call", name="search", input="same query", output="same result")
    ] * 8
    result = check(steps=steps, max_consecutive_repeats=5)
    assert result.passed is False
    assert result.score < 1.0
    assert "consecutive_repeats" in result.details
    assert result.details["consecutive_repeats"]["tool_name"] == "search"
    assert result.details["consecutive_repeats"]["count"] >= 8


def test_cycle_pattern_detected():
    """A-B-A-B repeating cycle triggers detection."""
    cycle = [
        StepRecord(step_type="tool_call", name="search", input="q", output="r"),
        StepRecord(step_type="tool_call", name="parse", input="r", output="p"),
    ]
    steps = cycle * 6  # 12 steps, 6 repetitions of A-B
    result = check(steps=steps, max_cycle_repeats=4)
    assert result.passed is False
    assert result.score < 1.0
    assert "cycle" in result.details


def test_near_threshold_passes():
    """Consecutive repeats just at the threshold should still pass."""
    steps = [
        StepRecord(step_type="tool_call", name="search", input="q", output="r")
    ] * 5
    result = check(steps=steps, max_consecutive_repeats=5)
    assert result.passed is True


def test_custom_thresholds():
    """Custom thresholds are respected."""
    steps = [
        StepRecord(step_type="tool_call", name="search", input="q", output="r")
    ] * 4
    # Default max_consecutive_repeats=5 → pass
    assert check(steps=steps).passed is True
    # Stricter threshold → fail
    assert check(steps=steps, max_consecutive_repeats=3).passed is False


def test_score_degrades_with_severity():
    """Score should be lower for worse loops."""
    mild = [
        StepRecord(step_type="tool_call", name="search", input="q", output="r")
    ] * 8
    severe = [
        StepRecord(step_type="tool_call", name="search", input="q", output="r")
    ] * 50
    mild_result = check(steps=mild, max_consecutive_repeats=5)
    severe_result = check(steps=severe, max_consecutive_repeats=5)
    assert severe_result.score < mild_result.score
```

**Step 2: Run tests to verify they fail**

Run: `cd services/verification-engine && python -m pytest tests/test_tool_loop.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.tool_loop'`

**Step 3: Write the implementation**

File: `services/verification-engine/engine/tool_loop.py`

```python
"""Deterministic tool loop / cycle detection check.

Analyzes the steps list for three loop signals:
1. Excessive total tool call count
2. Consecutive repeated identical tool calls
3. Cyclic patterns (A-B-A-B or A-B-C-A-B-C)

This check is fully deterministic and does not require LLM calls.
"""

import logging
from typing import List, Optional

from engine.models import CheckResult

logger = logging.getLogger("agentguard.verification-engine.tool_loop")

DEFAULT_MAX_TOOL_CALLS = 25
DEFAULT_MAX_CONSECUTIVE_REPEATS = 5
DEFAULT_MAX_CYCLE_REPEATS = 4


def _count_consecutive_repeats(tool_names: List[str]) -> tuple:
    """Find the longest run of consecutive identical tool calls.

    Returns:
        (tool_name, count) of the longest consecutive run.
    """
    if not tool_names:
        return ("", 0)

    max_name = tool_names[0]
    max_count = 1
    current_name = tool_names[0]
    current_count = 1

    for name in tool_names[1:]:
        if name == current_name:
            current_count += 1
        else:
            if current_count > max_count:
                max_count = current_count
                max_name = current_name
            current_name = name
            current_count = 1

    if current_count > max_count:
        max_count = current_count
        max_name = current_name

    return (max_name, max_count)


def _detect_cycle(tool_names: List[str], max_cycle_repeats: int) -> Optional[dict]:
    """Detect repeating cycle patterns in tool call sequence.

    Tries cycle lengths from 2 up to len/max_cycle_repeats.
    A cycle is confirmed when the same sequence repeats >= max_cycle_repeats times.

    Returns:
        Dict with cycle info if detected, None otherwise.
    """
    n = len(tool_names)
    if n < 4:
        return None

    max_cycle_len = n // max_cycle_repeats
    for cycle_len in range(2, max_cycle_len + 1):
        pattern = tool_names[:cycle_len]
        repeats = 0
        for start in range(0, n - cycle_len + 1, cycle_len):
            if tool_names[start:start + cycle_len] == pattern:
                repeats += 1
            else:
                break

        if repeats >= max_cycle_repeats:
            return {
                "pattern": pattern,
                "cycle_length": cycle_len,
                "repeats": repeats,
            }

    return None


def check(
    steps: list,
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
    max_consecutive_repeats: int = DEFAULT_MAX_CONSECUTIVE_REPEATS,
    max_cycle_repeats: int = DEFAULT_MAX_CYCLE_REPEATS,
) -> CheckResult:
    """Check for tool call loops and cycles in agent steps.

    Args:
        steps: List of StepRecord-like objects with step_type and name.
        max_tool_calls: Maximum total tool calls before flagging.
        max_consecutive_repeats: Maximum consecutive identical tool calls.
        max_cycle_repeats: Minimum cycle repetitions to detect a pattern.

    Returns:
        CheckResult with a loop severity score.
        If no steps or no tool calls, returns passed with skipped=True.
    """
    # Filter to tool calls only
    tool_calls = [s for s in steps if getattr(s, "step_type", None) == "tool_call"]

    if not tool_calls:
        return CheckResult(
            check_type="tool_loop",
            score=1.0,
            passed=True,
            details={"skipped": True},
        )

    tool_names = [getattr(s, "name", "") for s in tool_calls]
    total_count = len(tool_names)
    issues = {}

    # Check 1: Excessive total tool calls
    if total_count > max_tool_calls:
        issues["excessive_count"] = {
            "total": total_count,
            "threshold": max_tool_calls,
        }

    # Check 2: Consecutive repeats
    repeat_name, repeat_count = _count_consecutive_repeats(tool_names)
    if repeat_count > max_consecutive_repeats:
        issues["consecutive_repeats"] = {
            "tool_name": repeat_name,
            "count": repeat_count,
            "threshold": max_consecutive_repeats,
        }

    # Check 3: Cycle detection
    cycle = _detect_cycle(tool_names, max_cycle_repeats)
    if cycle is not None:
        issues["cycle"] = cycle

    if not issues:
        return CheckResult(
            check_type="tool_loop",
            score=1.0,
            passed=True,
            details={"tool_call_count": total_count},
        )

    # Compute severity score: worse loops → lower score
    # Base: how far over the thresholds we are
    severity = 0.0

    if "excessive_count" in issues:
        ratio = total_count / max_tool_calls
        severity = max(severity, min(1.0, (ratio - 1.0) / 2.0))

    if "consecutive_repeats" in issues:
        ratio = repeat_count / max_consecutive_repeats
        severity = max(severity, min(1.0, (ratio - 1.0) / 3.0))

    if "cycle" in issues:
        ratio = cycle["repeats"] / max_cycle_repeats
        severity = max(severity, min(1.0, (ratio - 1.0) / 2.0))

    score = max(0.0, 1.0 - severity)

    return CheckResult(
        check_type="tool_loop",
        score=round(score, 4),
        passed=False,
        details=issues,
    )
```

**Step 4: Run tests to verify they pass**

Run: `cd services/verification-engine && python -m pytest tests/test_tool_loop.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add services/verification-engine/engine/tool_loop.py services/verification-engine/tests/test_tool_loop.py
git commit -m "feat: add tool loop / cycle detection check module"
```

---

### Task 2: Integrate tool_loop into the verification pipeline

**Files:**
- Modify: `services/verification-engine/engine/pipeline.py`
- Modify: `services/verification-engine/tests/test_pipeline.py`

**Step 1: Write the failing test**

Add to `services/verification-engine/tests/test_pipeline.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from shared.models import StepRecord


@pytest.mark.asyncio
async def test_pipeline_runs_tool_loop_check_when_steps_provided():
    """Pipeline includes tool_loop check when steps are passed."""
    from engine.pipeline import verify

    steps = [
        StepRecord(step_type="tool_call", name="search", input="q", output="r"),
        StepRecord(step_type="tool_call", name="read", input="f", output="d"),
    ]

    with patch("engine.hallucination.check", new_callable=AsyncMock) as mock_hal, \
         patch("engine.drift.check", new_callable=AsyncMock) as mock_drift:
        from engine.models import CheckResult
        mock_hal.return_value = CheckResult(check_type="hallucination", score=1.0, passed=True, details={})
        mock_drift.return_value = CheckResult(check_type="drift", score=1.0, passed=True, details={})

        result = await verify(output="test output", steps=steps)

    assert "tool_loop" in result.checks
    assert result.checks["tool_loop"].passed is True


@pytest.mark.asyncio
async def test_pipeline_skips_tool_loop_when_no_steps():
    """Pipeline does not include tool_loop when no steps provided."""
    from engine.pipeline import verify

    with patch("engine.hallucination.check", new_callable=AsyncMock) as mock_hal, \
         patch("engine.drift.check", new_callable=AsyncMock) as mock_drift:
        from engine.models import CheckResult
        mock_hal.return_value = CheckResult(check_type="hallucination", score=1.0, passed=True, details={})
        mock_drift.return_value = CheckResult(check_type="drift", score=1.0, passed=True, details={})

        result = await verify(output="test output")

    assert "tool_loop" not in result.checks


@pytest.mark.asyncio
async def test_pipeline_tool_loop_failure_affects_confidence():
    """A tool loop detection failure lowers composite confidence."""
    from engine.pipeline import verify

    # Create a loop: same tool 30 times
    steps = [
        StepRecord(step_type="tool_call", name="search", input="q", output="r")
    ] * 30

    with patch("engine.hallucination.check", new_callable=AsyncMock) as mock_hal, \
         patch("engine.drift.check", new_callable=AsyncMock) as mock_drift:
        from engine.models import CheckResult
        mock_hal.return_value = CheckResult(check_type="hallucination", score=1.0, passed=True, details={})
        mock_drift.return_value = CheckResult(check_type="drift", score=1.0, passed=True, details={})

        result = await verify(output="test output", steps=steps)

    assert result.checks["tool_loop"].passed is False
    assert result.confidence is not None
    assert result.confidence < 1.0
```

**Step 2: Run tests to verify they fail**

Run: `cd services/verification-engine && python -m pytest tests/test_pipeline.py::test_pipeline_runs_tool_loop_check_when_steps_provided -v`
Expected: FAIL — `verify() got an unexpected keyword argument 'steps'`

**Step 3: Modify the pipeline**

In `services/verification-engine/engine/pipeline.py`, add the import and modify `verify()`:

Add import at top:
```python
from engine import tool_loop
```

Add `steps` parameter to `verify()` signature:
```python
async def verify(
    output: Any,
    task: Optional[str] = None,
    schema: Optional[Dict[str, Any]] = None,
    ground_truth: Any = None,
    conversation_history: Optional[List[ConversationTurn]] = None,
    config: Optional[VerificationConfig] = None,
    steps: Optional[list] = None,
) -> VerificationResult:
```

Add tool loop check after schema validation, before LLM checks:
```python
    # 1b. Tool loop detection (deterministic, sync)
    tool_loop_result = None
    if steps:
        tool_loop_result = tool_loop.check(steps=steps)
```

Add to the `checks` dict assembly:
```python
    if tool_loop_result is not None:
        checks["tool_loop"] = tool_loop_result
```

Add tool_loop weight handling (same pattern as coherence — dynamic rebalancing):
```python
    TOOL_LOOP_WEIGHT = 0.15

    if tool_loop_result is not None:
        # Rebalance weights to include tool_loop
        original_total = sum(weights.values())
        if original_total > 0:
            scale = (original_total - TOOL_LOOP_WEIGHT) / original_total
            weights = {k: v * scale for k, v in weights.items()}
        weights["tool_loop"] = TOOL_LOOP_WEIGHT
```

**Step 4: Run all pipeline tests**

Run: `cd services/verification-engine && python -m pytest tests/test_pipeline.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add services/verification-engine/engine/pipeline.py services/verification-engine/tests/test_pipeline.py
git commit -m "feat: integrate tool loop check into verification pipeline"
```

---

### Task 3: Pass steps from async-worker and sync-gateway to pipeline

**Files:**
- Modify: `services/async-worker/app/worker.py`
- Modify: `services/sync-gateway/app/routes.py`

**Step 1: Modify async-worker to pass steps**

In `services/async-worker/app/worker.py`, add `steps=event.steps` to the `verify()` call:

```python
        result = await verify(
            output=event.output,
            task=event.task,
            schema=event.schema_definition,
            ground_truth=event.ground_truth,
            conversation_history=event.conversation_history,
            steps=event.steps,
        )
```

**Step 2: Modify sync-gateway to pass steps**

In `services/sync-gateway/app/routes.py`, in `_verify_and_correct()`, add `steps` to both `run_verification()` calls:

Initial verification:
```python
    result = await run_verification(
        output=event.output,
        task=event.task,
        schema=event.schema_definition,
        ground_truth=event.ground_truth,
        conversation_history=event.conversation_history,
        config=config,
        steps=getattr(event, "steps", None),
    )
```

Re-verification after correction (pass the same steps — they don't change):
```python
            result = await run_verification(
                output=attempt.corrected_output,
                task=event.task,
                schema=event.schema_definition,
                ground_truth=event.ground_truth,
                conversation_history=event.conversation_history,
                config=config,
                steps=getattr(event, "steps", None),
            )
```

Note: `VerifyRequest` inherits from `IngestEvent` which has `steps`. Using `getattr` for safety.

**Step 3: Run existing tests to verify nothing broke**

Run: `cd services/verification-engine && python -m pytest tests/ -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add services/async-worker/app/worker.py services/sync-gateway/app/routes.py
git commit -m "feat: pass steps to verification pipeline for tool loop detection"
```

---

### Task 4: Add tool_loop check_type to dashboard display

**Files:**
- Modify: `nextjs-application/apps/web/app/home/[account]/sessions/[sessionId]/_components/session-timeline.tsx`

**Step 1: Add tool_loop to CHECK_TYPE_LABELS**

```typescript
const CHECK_TYPE_LABELS: Record<string, string> = {
  schema: 'Schema',
  hallucination: 'Hallucination',
  drift: 'Drift',
  coherence: 'Coherence',
  tool_loop: 'Tool Loop',
};
```

**Step 2: Verify build passes**

Run: `cd nextjs-application && pnpm --filter web typecheck 2>&1 | grep session`
Expected: No errors from session files

**Step 3: Commit**

```bash
cd nextjs-application
git add apps/web/app/home/[account]/sessions/[sessionId]/_components/session-timeline.tsx
git commit -m "feat: display tool_loop check results in session timeline"
```

---

### Task 5: Run full test suite and push

**Step 1: Run all verification engine tests**

Run: `cd services/verification-engine && python -m pytest tests/ -v`
Expected: ALL PASS

**Step 2: Run landing page build**

Run: `cd nextjs-application && pnpm --filter landing build`
Expected: Build succeeds

**Step 3: Push submodule and parent**

```bash
cd nextjs-application && git push
cd .. && git add nextjs-application services/ && git commit -m "feat: tool loop / cycle detection (Phase 1.1)" && git push
```
