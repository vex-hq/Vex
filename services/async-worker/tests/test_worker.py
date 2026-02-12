"""Tests for the async verification worker."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from engine.models import CheckResult, VerificationResult
from shared.models import ConversationTurn, IngestEvent

from app.worker import process_event


@pytest.fixture
def sample_event():
    return IngestEvent(
        execution_id="exec-test-456",
        agent_id="test-bot",
        task="Answer questions",
        input={"query": "hello"},
        output={"response": "world"},
        ground_truth={"expected": "world"},
    )


@pytest.mark.asyncio
async def test_process_event_returns_verified_dict(sample_event):
    mock_result = VerificationResult(
        confidence=0.85,
        action="pass",
        checks={
            "schema": CheckResult(check_type="schema", score=1.0, passed=True),
            "hallucination": CheckResult(check_type="hallucination", score=0.8, passed=True),
            "drift": CheckResult(check_type="drift", score=0.75, passed=True),
        },
    )

    with patch("app.worker.verify", new_callable=AsyncMock, return_value=mock_result):
        result = await process_event(sample_event)

    assert result["execution_id"] == "exec-test-456"
    assert result["agent_id"] == "test-bot"
    assert result["confidence"] == "0.85"
    assert result["action"] == "pass"

    checks = json.loads(result["checks"])
    assert "schema" in checks
    assert "hallucination" in checks
    assert "drift" in checks
    assert checks["schema"]["passed"] is True


@pytest.mark.asyncio
async def test_process_event_flag_action(sample_event):
    mock_result = VerificationResult(
        confidence=0.6,
        action="flag",
        checks={
            "schema": CheckResult(check_type="schema", score=0.0, passed=False),
        },
    )

    with patch("app.worker.verify", new_callable=AsyncMock, return_value=mock_result):
        result = await process_event(sample_event)

    assert result["action"] == "flag"
    assert result["confidence"] == "0.6"


@pytest.mark.asyncio
async def test_process_event_handles_engine_error(sample_event):
    with patch("app.worker.verify", new_callable=AsyncMock, side_effect=RuntimeError("LLM down")):
        result = await process_event(sample_event)

    assert result["execution_id"] == "exec-test-456"
    assert result["action"] == "pass"
    assert result["confidence"] == ""


@pytest.mark.asyncio
async def test_process_event_none_confidence(sample_event):
    mock_result = VerificationResult(
        confidence=None,
        action="pass",
        checks={},
    )

    with patch("app.worker.verify", new_callable=AsyncMock, return_value=mock_result):
        result = await process_event(sample_event)

    assert result["confidence"] == ""
    assert result["action"] == "pass"


@pytest.mark.asyncio
async def test_process_event_forwards_conversation_history():
    """Conversation history from the event should be forwarded to the engine."""
    history = [
        ConversationTurn(sequence_number=0, input="Revenue?", output="$5.2B"),
    ]
    event = IngestEvent(
        execution_id="exec-hist-001",
        agent_id="test-bot",
        task="Financial summary",
        input={"query": "profit?"},
        output={"response": "$800M"},
        ground_truth={"profit": "$800M"},
        conversation_history=history,
    )

    mock_result = VerificationResult(
        confidence=0.9,
        action="pass",
        checks={
            "schema": CheckResult(check_type="schema", score=1.0, passed=True),
        },
    )

    with patch("app.worker.verify", new_callable=AsyncMock, return_value=mock_result) as mock_verify:
        result = await process_event(event)

    assert result["action"] == "pass"
    # Verify conversation_history was forwarded
    call_kwargs = mock_verify.call_args.kwargs
    assert "conversation_history" in call_kwargs
    assert call_kwargs["conversation_history"] is not None
    assert len(call_kwargs["conversation_history"]) == 1
    assert call_kwargs["conversation_history"][0].sequence_number == 0
