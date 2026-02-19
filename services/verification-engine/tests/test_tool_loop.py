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
