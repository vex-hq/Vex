"""Tests for the async verification worker."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from app.worker import process_event
from engine.models import CheckResult, VerificationResult
from shared.models import ConversationTurn, IngestEvent


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


@pytest.mark.asyncio
async def test_process_event_extracts_org_id_from_metadata():
    """org_id should be extracted from event metadata."""
    event = IngestEvent(
        execution_id="exec-org-1",
        agent_id="bot",
        input="x",
        output="y",
        metadata={"org_id": "my-org"},
    )
    mock_result = VerificationResult(confidence=0.9, action="pass", checks={})
    with patch("app.worker.verify", new_callable=AsyncMock, return_value=mock_result):
        result = await process_event(event)
    assert result["org_id"] == "my-org"


@pytest.mark.asyncio
async def test_process_event_default_org_id_when_no_metadata():
    """org_id should default to 'default' when metadata is empty."""
    event = IngestEvent(
        execution_id="exec-no-meta",
        agent_id="bot",
        input="x",
        output="y",
    )
    mock_result = VerificationResult(confidence=0.9, action="pass", checks={})
    with patch("app.worker.verify", new_callable=AsyncMock, return_value=mock_result):
        result = await process_event(event)
    assert result["org_id"] == "default"


@pytest.mark.asyncio
async def test_process_event_checks_serialized_correctly():
    """Check results should be serialized as a JSON string with expected structure."""
    event = IngestEvent(
        execution_id="exec-checks",
        agent_id="bot",
        input="x",
        output="y",
    )
    mock_result = VerificationResult(
        confidence=0.7,
        action="flag",
        checks={
            "hallucination": CheckResult(
                check_type="hallucination",
                score=0.3,
                passed=False,
                details={"claims": ["bad claim"]},
            ),
        },
    )
    with patch("app.worker.verify", new_callable=AsyncMock, return_value=mock_result):
        result = await process_event(event)

    checks = json.loads(result["checks"])
    assert checks["hallucination"]["check_type"] == "hallucination"
    assert checks["hallucination"]["score"] == 0.3
    assert checks["hallucination"]["passed"] is False
    assert checks["hallucination"]["details"]["claims"] == ["bad claim"]


# --- Consumer loop tests ---


@pytest.mark.asyncio
async def test_run_skips_already_verified_events():
    """Events with already_verified=True in metadata should be ACKed and skipped."""
    import asyncio
    from app.main import run, STREAM_KEY, CONSUMER_GROUP

    mock_redis = AsyncMock()
    mock_redis.xgroup_create = AsyncMock()

    event = IngestEvent(
        execution_id="exec-skip",
        agent_id="bot",
        input="x",
        output="y",
        metadata={"already_verified": True, "org_id": "test"},
    )

    call_count = 0

    async def mock_xreadgroup(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [(STREAM_KEY, [("msg-1", {"data": event.model_dump_json()})])]
        raise asyncio.CancelledError()

    mock_redis.xreadgroup = mock_xreadgroup
    mock_redis.xack = AsyncMock()
    mock_redis.xadd = AsyncMock()

    with patch("app.main.aioredis") as mock_aioredis:
        mock_aioredis.from_url.return_value = mock_redis
        with patch("app.main.process_event", new_callable=AsyncMock) as mock_process:
            with pytest.raises(asyncio.CancelledError):
                await run()

    # process_event should NOT have been called (event was skipped)
    mock_process.assert_not_called()
    # But the message should be ACKed
    mock_redis.xack.assert_called_once_with(STREAM_KEY, CONSUMER_GROUP, "msg-1")


@pytest.mark.asyncio
async def test_run_processes_normal_event():
    """Normal events should be processed, ACKed, and published to verified stream."""
    import asyncio
    from app.main import run, STREAM_KEY, CONSUMER_GROUP, CONSUMER_NAME

    mock_redis = AsyncMock()
    mock_redis.xgroup_create = AsyncMock()

    event = IngestEvent(
        execution_id="exec-normal",
        agent_id="bot",
        input="x",
        output="y",
        metadata={"org_id": "test"},
    )

    call_count = 0

    async def mock_xreadgroup(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [(STREAM_KEY, [("msg-1", {"data": event.model_dump_json()})])]
        raise asyncio.CancelledError()

    mock_redis.xreadgroup = mock_xreadgroup
    mock_redis.xack = AsyncMock()
    mock_redis.xadd = AsyncMock()

    verified_data = {"execution_id": "exec-normal", "action": "pass"}

    with patch("app.main.aioredis") as mock_aioredis:
        mock_aioredis.from_url.return_value = mock_redis
        with patch("app.main.process_event", new_callable=AsyncMock, return_value=verified_data):
            with pytest.raises(asyncio.CancelledError):
                await run()

    mock_redis.xack.assert_called_once()
    # Verified result published to executions.verified
    mock_redis.xadd.assert_called_once()


@pytest.mark.asyncio
async def test_run_continues_on_per_message_error():
    """Per-message processing errors should be logged but not crash the loop."""
    import asyncio
    from app.main import run, STREAM_KEY

    mock_redis = AsyncMock()
    mock_redis.xgroup_create = AsyncMock()

    call_count = 0

    async def mock_xreadgroup(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [(STREAM_KEY, [("msg-1", {"data": "invalid json!!!"})])]
        raise asyncio.CancelledError()

    mock_redis.xreadgroup = mock_xreadgroup
    mock_redis.xack = AsyncMock()
    mock_redis.xadd = AsyncMock()

    with patch("app.main.aioredis") as mock_aioredis:
        mock_aioredis.from_url.return_value = mock_redis
        with pytest.raises(asyncio.CancelledError):
            await run()

    # The loop continued past the error (xack not called for failed message)
    mock_redis.xack.assert_not_called()
