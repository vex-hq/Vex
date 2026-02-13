import json
import pytest
from unittest.mock import MagicMock
from shared.models import IngestEvent
from app.worker import process_event, process_verified_event


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
        sample_event, s3_client=mock_s3, db_session=mock_db_session, org_id="org-1",
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
        "checks": json.dumps({
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
        }),
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
        "checks": json.dumps({
            "schema": {"check_type": "schema", "score": 1.0, "passed": True, "details": {}},
        }),
        "corrected": "True",
        "correction_attempts": json.dumps([
            {"layer": 1, "layer_name": "repair", "success": True, "latency_ms": 340.0},
        ]),
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
        "correction_attempts": json.dumps([
            {"layer": 1, "layer_name": "repair", "success": False},
            {"layer": 2, "layer_name": "constrained_regen", "success": True},
        ]),
        "original_output": json.dumps("bad output"),
    }
    result = process_verified_event(event, mock_db_session)
    assert result["corrected"] is True
