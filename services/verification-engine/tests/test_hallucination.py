"""Tests for the hallucination detection check."""

from unittest.mock import AsyncMock, patch

import pytest

from engine.hallucination import check
from engine.models import ConversationTurn


@pytest.mark.asyncio
async def test_grounded_claims_high_score():
    mock_response = {
        "claims": ["Alice is 30 years old", "Alice lives in NYC"],
        "grounded": ["Alice is 30 years old", "Alice lives in NYC"],
        "ungrounded": [],
        "score": 1.0,
    }
    with patch("engine.hallucination.call_llm", new_callable=AsyncMock, return_value=mock_response):
        result = await check(
            output="Alice is 30 years old and lives in NYC.",
            ground_truth={"name": "Alice", "age": 30, "city": "NYC"},
        )
    assert result.check_type == "hallucination"
    assert result.score == 1.0
    assert result.passed is True
    assert len(result.details["ungrounded"]) == 0


@pytest.mark.asyncio
async def test_ungrounded_claims_low_score():
    mock_response = {
        "claims": ["Alice is 30", "Alice is a doctor"],
        "grounded": ["Alice is 30"],
        "ungrounded": ["Alice is a doctor"],
        "score": 0.3,
    }
    with patch("engine.hallucination.call_llm", new_callable=AsyncMock, return_value=mock_response):
        result = await check(
            output="Alice is 30 and a doctor.",
            ground_truth={"name": "Alice", "age": 30},
        )
    assert result.score == 0.3
    assert result.passed is False
    assert "Alice is a doctor" in result.details["ungrounded"]


@pytest.mark.asyncio
async def test_no_ground_truth_skips():
    result = await check(output="any output", ground_truth=None)
    assert result.check_type == "hallucination"
    assert result.score == 1.0
    assert result.passed is True
    assert result.details["skipped"] is True


@pytest.mark.asyncio
async def test_timeout_returns_none_score():
    with patch("engine.hallucination.call_llm", new_callable=AsyncMock, return_value=None):
        result = await check(
            output="some output",
            ground_truth={"data": "reference"},
        )
    assert result.check_type == "hallucination"
    assert result.score is None
    assert result.passed is True
    assert result.details["error"] == "timeout"


@pytest.mark.asyncio
async def test_score_clamped_to_valid_range():
    mock_response = {
        "claims": [],
        "grounded": [],
        "ungrounded": [],
        "score": 1.5,
    }
    with patch("engine.hallucination.call_llm", new_callable=AsyncMock, return_value=mock_response):
        result = await check(
            output="output",
            ground_truth={"data": "truth"},
        )
    assert result.score == 1.0


# --- Conversation-aware hallucination tests ---


@pytest.mark.asyncio
async def test_conversation_prompt_used_with_history():
    """When conversation history is provided, the conversation-aware prompt is used."""
    mock_response = {
        "claims": ["Revenue is $5.2B"],
        "grounded": ["Revenue is $5.2B"],
        "ungrounded": [],
        "cross_turn_issues": [],
        "score": 1.0,
    }
    history = [
        ConversationTurn(sequence_number=0, input="What is revenue?", output="Revenue is $5.2B."),
    ]
    with patch("engine.hallucination.call_llm", new_callable=AsyncMock, return_value=mock_response) as mock_llm:
        result = await check(
            output="As I said, revenue is $5.2B.",
            ground_truth={"revenue": "$5.2B"},
            conversation_history=history,
        )
    # Verify conversation-aware system prompt was used
    call_kwargs = mock_llm.call_args
    assert "multi-turn" in call_kwargs.kwargs.get("system", call_kwargs[1].get("system", ""))
    assert "Conversation history" in call_kwargs.args[0]
    assert result.score == 1.0


@pytest.mark.asyncio
async def test_cross_turn_issue_detected():
    """Cross-turn hallucination should be reported in details."""
    mock_response = {
        "claims": ["I said revenue was $10B"],
        "grounded": [],
        "ungrounded": ["I said revenue was $10B"],
        "cross_turn_issues": ["Agent claims it said $10B in turn 0 but actually said $5.2B"],
        "score": 0.2,
    }
    history = [
        ConversationTurn(sequence_number=0, input="What is revenue?", output="Revenue is $5.2B."),
    ]
    with patch("engine.hallucination.call_llm", new_callable=AsyncMock, return_value=mock_response):
        result = await check(
            output="As I mentioned earlier, revenue was $10B.",
            ground_truth={"revenue": "$5.2B"},
            conversation_history=history,
        )
    assert result.score == 0.2
    assert result.passed is False
    assert "cross_turn_issues" in result.details
    assert len(result.details["cross_turn_issues"]) == 1


@pytest.mark.asyncio
async def test_single_shot_unchanged_with_none_history():
    """With None history, behavior is identical to the original single-shot check."""
    mock_response = {
        "claims": ["Claim A"],
        "grounded": ["Claim A"],
        "ungrounded": [],
        "score": 1.0,
    }
    with patch("engine.hallucination.call_llm", new_callable=AsyncMock, return_value=mock_response) as mock_llm:
        result = await check(
            output="Claim A",
            ground_truth={"data": "ref"},
            conversation_history=None,
        )
    # Verify single-shot system prompt was used (no "multi-turn")
    call_kwargs = mock_llm.call_args
    system_arg = call_kwargs.kwargs.get("system", call_kwargs[1].get("system", ""))
    assert "multi-turn" not in system_arg
    assert result.score == 1.0


@pytest.mark.asyncio
async def test_empty_history_uses_single_shot():
    """With empty list history, falls through to single-shot (no history content)."""
    mock_response = {
        "claims": [],
        "grounded": [],
        "ungrounded": [],
        "score": 1.0,
    }
    with patch("engine.hallucination.call_llm", new_callable=AsyncMock, return_value=mock_response) as mock_llm:
        result = await check(
            output="output",
            ground_truth={"data": "ref"},
            conversation_history=[],
        )
    call_kwargs = mock_llm.call_args
    system_arg = call_kwargs.kwargs.get("system", call_kwargs[1].get("system", ""))
    assert "multi-turn" not in system_arg
    assert result.score == 1.0
