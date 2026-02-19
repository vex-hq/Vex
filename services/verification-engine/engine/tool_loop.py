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
