import json
from unittest.mock import MagicMock

import pytest
from app.worker import process_event, process_verified_event
from shared.models import IngestEvent, StepRecord


@pytest.fixture
def sample_event():
    return IngestEvent(
        execution_id="exec-test-123",
        agent_id="test-bot",
        task="Answer questions",
        input={"query": "hello"},
        output={"response": "world"},
        token_count=150,
        cost_estimate=0.0003,
        latency_ms=320.5,
    )


@pytest.fixture
def mock_s3():
    mock = MagicMock()
    mock.put_object = MagicMock()
    return mock


@pytest.fixture
def mock_db_session():
    mock = MagicMock()
    execute_result = MagicMock()
    execute_result.rowcount = 1
    mock.execute = MagicMock(return_value=execute_result)
    mock.commit = MagicMock()
    mock.rollback = MagicMock()
    return mock


def test_process_event_writes_to_s3(sample_event, mock_s3, mock_db_session):
    process_event(sample_event, s3_client=mock_s3, db_session=mock_db_session, org_id="org-1")
    mock_s3.put_object.assert_called_once()
    call_kwargs = mock_s3.put_object.call_args[1]
    assert call_kwargs["Bucket"] == "agentguard-traces"
    assert "exec-test-123" in call_kwargs["Key"]


def test_process_event_writes_to_db(sample_event, mock_s3, mock_db_session):
    process_event(sample_event, s3_client=mock_s3, db_session=mock_db_session, org_id="org-1")
    # 2 execute calls: agent upsert + execution insert
    assert mock_db_session.execute.call_count == 2
    mock_db_session.commit.assert_called_once()


def test_process_event_s3_key_format(sample_event, mock_s3, mock_db_session):
    process_event(sample_event, s3_client=mock_s3, db_session=mock_db_session, org_id="org-1")
    call_kwargs = mock_s3.put_object.call_args[1]
    key = call_kwargs["Key"]
    assert key.startswith("org-1/test-bot/")
    assert key.endswith("exec-test-123.json")


def test_process_event_s3_payload_is_valid_json(sample_event, mock_s3, mock_db_session):
    process_event(sample_event, s3_client=mock_s3, db_session=mock_db_session, org_id="org-1")
    body = mock_s3.put_object.call_args[1]["Body"]
    parsed = json.loads(body)
    assert parsed["agent_id"] == "test-bot"
    assert parsed["execution_id"] == "exec-test-123"


def test_process_event_db_params(sample_event, mock_s3, mock_db_session):
    process_event(sample_event, s3_client=mock_s3, db_session=mock_db_session, org_id="org-1")
    # Second execute call is the execution insert (first is agent upsert)
    call_args = mock_db_session.execute.call_args_list[1]
    params = call_args[0][1]  # second positional arg is the params dict
    assert params["execution_id"] == "exec-test-123"
    assert params["agent_id"] == "test-bot"
    assert params["org_id"] == "org-1"
    assert params["latency_ms"] == 320.5
    assert params["token_count"] == 150
    assert "s3://agentguard-traces/" in params["trace_payload_ref"]


def test_process_event_db_params_include_cost_estimate(sample_event, mock_s3, mock_db_session):
    process_event(sample_event, s3_client=mock_s3, db_session=mock_db_session, org_id="org-1")
    # Second execute call is the execution insert
    call_args = mock_db_session.execute.call_args_list[1]
    params = call_args[0][1]
    assert params["cost_estimate"] == 0.0003


def test_session_fields_stored(sample_event, mock_s3, mock_db_session):
    sample_event.session_id = "sess-123"
    sample_event.parent_execution_id = "parent-456"
    sample_event.sequence_number = 2
    result = process_event(sample_event, mock_s3, mock_db_session, "org-1")
    assert result["session_id"] == "sess-123"
    assert result["parent_execution_id"] == "parent-456"
    assert result["sequence_number"] == 2
    # Verify DB params (second execute call is execution insert)
    call_args = mock_db_session.execute.call_args_list[1]
    params = call_args[0][1]
    assert params["session_id"] == "sess-123"
    assert params["parent_execution_id"] == "parent-456"
    assert params["sequence_number"] == 2


def test_session_fields_default_none(sample_event, mock_s3, mock_db_session):
    result = process_event(sample_event, mock_s3, mock_db_session, "org-1")
    assert result["session_id"] is None
    assert result["parent_execution_id"] is None
    assert result["sequence_number"] is None
    # Second execute call is execution insert
    call_args = mock_db_session.execute.call_args_list[1]
    params = call_args[0][1]
    assert params["session_id"] is None
    assert params["sequence_number"] is None


def test_process_event_upserts_agent(sample_event, mock_s3, mock_db_session):
    process_event(sample_event, s3_client=mock_s3, db_session=mock_db_session, org_id="org-1")
    # First execute call is the agent upsert
    agent_call = mock_db_session.execute.call_args_list[0]
    params = agent_call[0][1]
    assert params["agent_id"] == "test-bot"
    assert params["org_id"] == "org-1"
    assert params["name"] == "test-bot"
    assert params["task"] == "Answer questions"


def test_process_event_returns_stored_notification(sample_event, mock_s3, mock_db_session):
    result = process_event(
        sample_event,
        s3_client=mock_s3,
        db_session=mock_db_session,
        org_id="org-1",
    )
    assert result["execution_id"] == "exec-test-123"
    assert result["agent_id"] == "test-bot"
    assert result["org_id"] == "org-1"
    assert result["action"] == "pass"
    assert result["latency_ms"] == 320.5
    assert result["token_count"] == 150
    assert result["cost_estimate"] == 0.0003
    assert "s3://agentguard-traces/" in result["trace_payload_ref"]
    assert "timestamp" in result


# --- Tests for process_verified_event ---


@pytest.fixture
def verified_event():
    return {
        "execution_id": "exec-test-123",
        "agent_id": "test-bot",
        "confidence": "0.85",
        "action": "pass",
        "checks": json.dumps(
            {
                "schema": {
                    "check_type": "schema",
                    "score": 1.0,
                    "passed": True,
                    "details": {},
                },
                "hallucination": {
                    "check_type": "hallucination",
                    "score": 0.8,
                    "passed": True,
                    "details": {"claims": ["claim1"]},
                },
                "drift": {
                    "check_type": "drift",
                    "score": 0.75,
                    "passed": True,
                    "details": {"explanation": "relevant"},
                },
            }
        ),
    }


def test_process_verified_event_writes_check_results(verified_event, mock_db_session):
    result = process_verified_event(verified_event, mock_db_session)

    # Should write 3 check_results rows + 1 update execution = 4 execute calls
    assert mock_db_session.execute.call_count == 4
    mock_db_session.commit.assert_called_once()

    assert result["execution_id"] == "exec-test-123"
    assert result["action"] == "pass"
    assert result["confidence"] == 0.85
    assert result["checks_stored"] == 3


def test_process_verified_event_updates_execution(verified_event, mock_db_session):
    process_verified_event(verified_event, mock_db_session)

    # The first execute call should be the UPDATE (runs before check_results)
    first_call = mock_db_session.execute.call_args_list[0]
    params = first_call[0][1]
    assert params["execution_id"] == "exec-test-123"
    assert params["confidence"] == 0.85
    assert params["action"] == "pass"


def test_process_verified_event_null_confidence(mock_db_session):
    event = {
        "execution_id": "exec-null",
        "agent_id": "bot",
        "confidence": "",
        "action": "pass",
        "checks": "{}",
    }
    result = process_verified_event(event, mock_db_session)
    assert result["confidence"] is None
    # Only the UPDATE call (no check_results since checks is empty)
    assert mock_db_session.execute.call_count == 1


# --- Correction persistence tests ---


def test_process_verified_event_with_correction(mock_db_session):
    """process_verified_event should persist corrected=True and correction metadata."""
    event = {
        "execution_id": "exec-corrected",
        "agent_id": "test-bot",
        "confidence": "0.9",
        "action": "pass",
        "checks": json.dumps(
            {
                "schema": {"check_type": "schema", "score": 1.0, "passed": True, "details": {}},
            }
        ),
        "corrected": "True",
        "correction_attempts": json.dumps(
            [
                {"layer": 1, "layer_name": "repair", "success": True, "latency_ms": 340.0},
            ]
        ),
    }
    result = process_verified_event(event, mock_db_session)
    assert result["corrected"] is True

    # The UPDATE call (first) should include corrected=True
    update_call = mock_db_session.execute.call_args_list[0]
    params = update_call[0][1]
    assert params["corrected"] is True


def test_process_verified_event_without_correction(mock_db_session):
    """process_verified_event without correction data -> corrected=False."""
    event = {
        "execution_id": "exec-no-correct",
        "agent_id": "test-bot",
        "confidence": "0.8",
        "action": "pass",
        "checks": "{}",
    }
    result = process_verified_event(event, mock_db_session)
    assert result["corrected"] is False

    update_call = mock_db_session.execute.call_args_list[0]
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
        "correction_attempts": json.dumps(
            [
                {"layer": 1, "layer_name": "repair", "success": False},
                {"layer": 2, "layer_name": "constrained_regen", "success": True},
            ]
        ),
        "original_output": json.dumps("bad output"),
    }
    result = process_verified_event(event, mock_db_session)
    assert result["corrected"] is True


# --- Tool calls persistence tests ---


def test_process_event_stores_tool_calls(mock_s3, mock_db_session):
    """Tool call steps are written to tool_calls table."""
    event = IngestEvent(
        execution_id="exec-tools-1",
        agent_id="tool-bot",
        task="Search and summarize",
        input="query",
        output="result",
        steps=[
            StepRecord(step_type="tool_call", name="search", input="q1", output="r1"),
            StepRecord(step_type="tool_call", name="read_file", input="f1", output="content"),
            StepRecord(step_type="llm", name="gpt-4", input="prompt", output="response"),
        ],
    )
    process_event(event, s3_client=mock_s3, db_session=mock_db_session, org_id="org-1")

    # 2 base calls (agent upsert + execution insert) + 2 tool_call inserts = 4
    assert mock_db_session.execute.call_count == 4

    # Check the tool_call insert params (3rd and 4th calls)
    tool_call_1 = mock_db_session.execute.call_args_list[2][0][1]
    assert tool_call_1["tool_name"] == "search"
    assert tool_call_1["sequence"] == 0
    assert tool_call_1["agent_id"] == "tool-bot"

    tool_call_2 = mock_db_session.execute.call_args_list[3][0][1]
    assert tool_call_2["tool_name"] == "read_file"
    assert tool_call_2["sequence"] == 1


def test_process_event_no_steps_no_tool_calls(sample_event, mock_s3, mock_db_session):
    """Events without steps should not insert any tool_calls rows."""
    process_event(sample_event, s3_client=mock_s3, db_session=mock_db_session, org_id="org-1")
    # Only 2 base calls (agent upsert + execution insert)
    assert mock_db_session.execute.call_count == 2


def test_process_event_filters_non_tool_steps(mock_s3, mock_db_session):
    """Only step_type='tool_call' steps are stored in tool_calls."""
    event = IngestEvent(
        execution_id="exec-mixed",
        agent_id="mixed-bot",
        task="Mixed steps",
        input="in",
        output="out",
        steps=[
            StepRecord(step_type="llm", name="gpt-4", input="p", output="r"),
            StepRecord(step_type="tool_call", name="search", input="q", output="r"),
            StepRecord(step_type="llm", name="gpt-4", input="p2", output="r2"),
        ],
    )
    process_event(event, s3_client=mock_s3, db_session=mock_db_session, org_id="org-1")
    # 2 base + 1 tool_call = 3
    assert mock_db_session.execute.call_count == 3


# --- Consumer loop tests ---


@pytest.mark.asyncio
async def test_ensure_consumer_group_creates_group():
    """_ensure_consumer_group should call xgroup_create."""
    from unittest.mock import AsyncMock
    from app.main import _ensure_consumer_group

    mock_redis = AsyncMock()
    mock_redis.xgroup_create = AsyncMock()
    await _ensure_consumer_group(mock_redis, "test.stream", "test-group")
    mock_redis.xgroup_create.assert_called_once_with(
        "test.stream", "test-group", id="0", mkstream=True
    )


@pytest.mark.asyncio
async def test_ensure_consumer_group_ignores_existing():
    """_ensure_consumer_group should not raise if group already exists."""
    from unittest.mock import AsyncMock
    from app.main import _ensure_consumer_group

    mock_redis = AsyncMock()
    mock_redis.xgroup_create = AsyncMock(
        side_effect=Exception("BUSYGROUP Consumer Group name already exists")
    )
    # Should not raise
    await _ensure_consumer_group(mock_redis, "test.stream", "test-group")


@pytest.mark.asyncio
async def test_consume_raw_processes_event_and_publishes():
    """_consume_raw should process events, ACK them, and publish to stored stream."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.main import _consume_raw, RAW_STREAM_KEY, RAW_CONSUMER_GROUP, STORED_STREAM_KEY

    mock_redis = AsyncMock()
    mock_s3 = MagicMock()

    event = IngestEvent(
        execution_id="exec-raw-1",
        agent_id="bot",
        input="x",
        output="y",
        metadata={"org_id": "org-1"},
    )

    call_count = 0

    async def mock_xreadgroup(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [(RAW_STREAM_KEY, [("msg-1", {"data": event.model_dump_json()})])]
        raise asyncio.CancelledError()

    mock_redis.xreadgroup = mock_xreadgroup
    mock_redis.xack = AsyncMock()
    mock_redis.xadd = AsyncMock()

    stored_notification = {"execution_id": "exec-raw-1", "action": "pass"}
    mock_session = MagicMock()

    with patch("app.main.SessionLocal", return_value=mock_session):
        with patch("app.main.process_event", return_value=stored_notification) as mock_process:
            with pytest.raises(asyncio.CancelledError):
                await _consume_raw(mock_redis, mock_s3)

    mock_process.assert_called_once()
    mock_redis.xack.assert_called_once_with(RAW_STREAM_KEY, RAW_CONSUMER_GROUP, "msg-1")
    mock_redis.xadd.assert_called_once()
    # Verify published to stored stream
    assert mock_redis.xadd.call_args[0][0] == STORED_STREAM_KEY
    mock_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_consume_raw_rolls_back_on_process_error():
    """_consume_raw should rollback DB session when process_event raises."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.main import _consume_raw, RAW_STREAM_KEY

    mock_redis = AsyncMock()
    mock_s3 = MagicMock()

    event = IngestEvent(
        execution_id="exec-err",
        agent_id="bot",
        input="x",
        output="y",
        metadata={"org_id": "org-1"},
    )

    call_count = 0

    async def mock_xreadgroup(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [(RAW_STREAM_KEY, [("msg-1", {"data": event.model_dump_json()})])]
        raise asyncio.CancelledError()

    mock_redis.xreadgroup = mock_xreadgroup
    mock_redis.xack = AsyncMock()
    mock_redis.xadd = AsyncMock()

    mock_session = MagicMock()

    with patch("app.main.SessionLocal", return_value=mock_session):
        with patch("app.main.process_event", side_effect=RuntimeError("DB error")):
            with pytest.raises(asyncio.CancelledError):
                await _consume_raw(mock_redis, mock_s3)

    mock_session.rollback.assert_called_once()
    mock_session.close.assert_called_once()
    # Message should NOT be ACKed
    mock_redis.xack.assert_not_called()


@pytest.mark.asyncio
async def test_consume_verified_processes_and_publishes():
    """_consume_verified should process verified events, ACK, and publish."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.main import _consume_verified, VERIFIED_STREAM_KEY, VERIFIED_CONSUMER_GROUP, STORED_STREAM_KEY

    mock_redis = AsyncMock()

    verified_data = json.dumps({
        "execution_id": "exec-v1",
        "agent_id": "bot",
        "confidence": "0.9",
        "action": "pass",
        "checks": "{}",
    })

    call_count = 0

    async def mock_xreadgroup(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [(VERIFIED_STREAM_KEY, [("msg-1", {"data": verified_data})])]
        raise asyncio.CancelledError()

    mock_redis.xreadgroup = mock_xreadgroup
    mock_redis.xack = AsyncMock()
    mock_redis.xadd = AsyncMock()

    updated_notification = {"execution_id": "exec-v1", "action": "pass"}
    mock_session = MagicMock()

    with patch("app.main.SessionLocal", return_value=mock_session):
        with patch("app.main.process_verified_event", return_value=updated_notification):
            with pytest.raises(asyncio.CancelledError):
                await _consume_verified(mock_redis)

    mock_redis.xack.assert_called_once_with(VERIFIED_STREAM_KEY, VERIFIED_CONSUMER_GROUP, "msg-1")
    mock_redis.xadd.assert_called_once()
    assert mock_redis.xadd.call_args[0][0] == STORED_STREAM_KEY


@pytest.mark.asyncio
async def test_consume_raw_fallback_org_id():
    """Events without org_id in metadata should use fallback 'default'."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.main import _consume_raw, RAW_STREAM_KEY

    mock_redis = AsyncMock()
    mock_s3 = MagicMock()

    event = IngestEvent(
        execution_id="exec-no-org",
        agent_id="bot",
        input="x",
        output="y",
    )

    call_count = 0

    async def mock_xreadgroup(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [(RAW_STREAM_KEY, [("msg-1", {"data": event.model_dump_json()})])]
        raise asyncio.CancelledError()

    mock_redis.xreadgroup = mock_xreadgroup
    mock_redis.xack = AsyncMock()
    mock_redis.xadd = AsyncMock()

    mock_session = MagicMock()

    with patch("app.main.SessionLocal", return_value=mock_session):
        with patch("app.main.process_event", return_value={"execution_id": "exec-no-org"}) as mock_process:
            with pytest.raises(asyncio.CancelledError):
                await _consume_raw(mock_redis, mock_s3)

    # Verify org_id fallback was used
    call_kwargs = mock_process.call_args
    assert call_kwargs[1]["org_id"] == "default" or call_kwargs.kwargs["org_id"] == "default"
