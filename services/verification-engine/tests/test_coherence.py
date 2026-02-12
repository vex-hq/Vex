"""Tests for the coherence detection check."""

from unittest.mock import AsyncMock, patch

import pytest

from engine.coherence import check
from engine.models import ConversationTurn


@pytest.mark.asyncio
async def test_no_history_skips():
    result = await check(output="any output", conversation_history=None)
    assert result.check_type == "coherence"
    assert result.score == 1.0
    assert result.passed is True
    assert result.details["skipped"] is True


@pytest.mark.asyncio
async def test_empty_history_skips():
    result = await check(output="any output", conversation_history=[])
    assert result.check_type == "coherence"
    assert result.score == 1.0
    assert result.passed is True
    assert result.details["skipped"] is True


@pytest.mark.asyncio
async def test_contradiction_detected():
    mock_response = {
        "contradictions": [
            {
                "prior_turn": 0,
                "prior_statement": "Revenue is $5.2B",
                "current_statement": "Revenue is $15B",
                "explanation": "Agent changed revenue figure without correction",
            }
        ],
        "score": 0.2,
    }
    history = [
        ConversationTurn(
            sequence_number=0,
            input="What is revenue?",
            output="Revenue is $5.2B.",
        ),
    ]
    with patch("engine.coherence.call_llm", new_callable=AsyncMock, return_value=mock_response):
        result = await check(output="Revenue is $15B.", conversation_history=history)

    assert result.check_type == "coherence"
    assert result.score == 0.2
    assert result.passed is False
    assert len(result.details["contradictions"]) == 1
    assert result.details["contradictions"][0]["prior_turn"] == 0


@pytest.mark.asyncio
async def test_consistent_output_passes():
    mock_response = {
        "contradictions": [],
        "score": 1.0,
    }
    history = [
        ConversationTurn(
            sequence_number=0,
            input="What is revenue?",
            output="Revenue is $5.2B.",
        ),
    ]
    with patch("engine.coherence.call_llm", new_callable=AsyncMock, return_value=mock_response):
        result = await check(
            output="As I mentioned, revenue is $5.2B.",
            conversation_history=history,
        )

    assert result.score == 1.0
    assert result.passed is True
    assert len(result.details["contradictions"]) == 0


@pytest.mark.asyncio
async def test_timeout_returns_none_score():
    history = [
        ConversationTurn(sequence_number=0, input="q", output="a"),
    ]
    with patch("engine.coherence.call_llm", new_callable=AsyncMock, return_value=None):
        result = await check(output="some output", conversation_history=history)

    assert result.check_type == "coherence"
    assert result.score is None
    assert result.passed is True
    assert result.details["error"] == "timeout"


@pytest.mark.asyncio
async def test_score_clamped_to_valid_range():
    mock_response = {
        "contradictions": [],
        "score": 1.5,
    }
    history = [
        ConversationTurn(sequence_number=0, input="q", output="a"),
    ]
    with patch("engine.coherence.call_llm", new_callable=AsyncMock, return_value=mock_response):
        result = await check(output="output", conversation_history=history)

    assert result.score == 1.0
