"""Tests for the task drift detection check."""

from unittest.mock import AsyncMock, patch

import pytest

from engine.drift import check
from engine.models import ConversationTurn


@pytest.mark.asyncio
async def test_relevant_output_high_score():
    mock_response = {
        "score": 0.95,
        "explanation": "Output directly addresses the billing question.",
    }
    with patch("engine.drift.call_llm", new_callable=AsyncMock, return_value=mock_response):
        result = await check(
            output="Your bill for January was $150.",
            task="Answer billing questions",
        )
    assert result.check_type == "drift"
    assert result.score == 0.95
    assert result.passed is True
    assert "billing" in result.details["explanation"].lower()


@pytest.mark.asyncio
async def test_irrelevant_output_low_score():
    mock_response = {
        "score": 0.1,
        "explanation": "Output discusses weather, not billing.",
    }
    with patch("engine.drift.call_llm", new_callable=AsyncMock, return_value=mock_response):
        result = await check(
            output="The weather today is sunny.",
            task="Answer billing questions",
        )
    assert result.score == 0.1
    assert result.passed is False


@pytest.mark.asyncio
async def test_no_task_skips():
    result = await check(output="any output", task=None)
    assert result.check_type == "drift"
    assert result.score == 1.0
    assert result.passed is True
    assert result.details["skipped"] is True


@pytest.mark.asyncio
async def test_timeout_returns_none_score():
    with patch("engine.drift.call_llm", new_callable=AsyncMock, return_value=None):
        result = await check(
            output="some output",
            task="some task",
        )
    assert result.check_type == "drift"
    assert result.score is None
    assert result.passed is True
    assert result.details["error"] == "timeout"


@pytest.mark.asyncio
async def test_score_clamped_to_valid_range():
    mock_response = {"score": -0.5, "explanation": "negative score"}
    with patch("engine.drift.call_llm", new_callable=AsyncMock, return_value=mock_response):
        result = await check(output="output", task="task")
    assert result.score == 0.0


# --- Conversation-aware drift tests ---


@pytest.mark.asyncio
async def test_trajectory_prompt_used_with_history():
    """When conversation history is provided, the trajectory-aware prompt is used."""
    mock_response = {
        "immediate_relevance": 0.9,
        "trajectory_drift": 0.85,
        "explanation": "Conversation stays on topic.",
    }
    history = [
        ConversationTurn(sequence_number=0, input="Tell me about ACME revenue", output="Revenue is $5.2B."),
    ]
    with patch("engine.drift.call_llm", new_callable=AsyncMock, return_value=mock_response) as mock_llm:
        result = await check(
            output="Profit margin was 15%.",
            task="Generate financial summary for ACME",
            conversation_history=history,
        )
    call_kwargs = mock_llm.call_args
    system_arg = call_kwargs.kwargs.get("system", call_kwargs[1].get("system", ""))
    assert "multi-turn" in system_arg
    assert "Conversation history" in call_kwargs.args[0]
    assert result.score == 0.85  # min(0.9, 0.85)
    assert result.details["immediate_relevance"] == 0.9
    assert result.details["trajectory_drift"] == 0.85


@pytest.mark.asyncio
async def test_progressive_drift_detected():
    """Progressive drift should result in low trajectory_drift score."""
    mock_response = {
        "immediate_relevance": 0.6,
        "trajectory_drift": 0.2,
        "explanation": "Conversation has gradually drifted off-topic.",
    }
    history = [
        ConversationTurn(sequence_number=0, input="ACME revenue?", output="$5.2B"),
        ConversationTurn(sequence_number=1, input="And profits?", output="$800M"),
        ConversationTurn(sequence_number=2, input="What about the weather?", output="It's sunny today"),
    ]
    with patch("engine.drift.call_llm", new_callable=AsyncMock, return_value=mock_response):
        result = await check(
            output="The forecast shows rain tomorrow.",
            task="Generate financial summary for ACME",
            conversation_history=history,
        )
    assert result.score == 0.2  # min(0.6, 0.2)
    assert result.passed is False


@pytest.mark.asyncio
async def test_single_shot_unchanged_without_history():
    """Without history, behavior is identical to the original single-shot check."""
    mock_response = {"score": 0.95, "explanation": "Output addresses billing."}
    with patch("engine.drift.call_llm", new_callable=AsyncMock, return_value=mock_response) as mock_llm:
        result = await check(
            output="Your bill is $150.",
            task="Answer billing questions",
            conversation_history=None,
        )
    call_kwargs = mock_llm.call_args
    system_arg = call_kwargs.kwargs.get("system", call_kwargs[1].get("system", ""))
    assert "multi-turn" not in system_arg
    assert result.score == 0.95


@pytest.mark.asyncio
async def test_empty_history_uses_single_shot():
    """With empty list history, uses single-shot prompt."""
    mock_response = {"score": 0.9, "explanation": "Relevant."}
    with patch("engine.drift.call_llm", new_callable=AsyncMock, return_value=mock_response) as mock_llm:
        result = await check(
            output="output",
            task="some task",
            conversation_history=[],
        )
    call_kwargs = mock_llm.call_args
    system_arg = call_kwargs.kwargs.get("system", call_kwargs[1].get("system", ""))
    assert "multi-turn" not in system_arg
    assert result.score == 0.9
