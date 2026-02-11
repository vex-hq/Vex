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
    """Schema-only failure -> Layer 1 (Repair)."""
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
    """Confidence > 0.5 -> Layer 1."""
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
    """Confidence between 0.3 and 0.5 -> Layer 2."""
    result = VerificationResult(
        confidence=0.4,
        action="block",
        checks={
            "hallucination": CheckResult(check_type="hallucination", score=0.2, passed=False),
        },
    )
    assert select_layer(result) == 2


def test_select_layer_severe_failure():
    """Confidence <= 0.3 -> Layer 3."""
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
    """None confidence -> Layer 3 (severe)."""
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
    """LLM timeout -> correction returns None corrected_output."""
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
    """LLM returns unexpected structure -> treated as failure."""
    with patch("engine.correction.call_llm", new_callable=AsyncMock, return_value={"unexpected": "data"}):
        result = await correct(
            layer=2,
            output="broken",
            task="task",
            checks={},
        )

    # Should still return a CorrectionAttempt even if output extraction fails
    assert isinstance(result, CorrectionAttempt)
