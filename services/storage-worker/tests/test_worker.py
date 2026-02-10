import json
import pytest
from unittest.mock import MagicMock
from shared.models import IngestEvent
from app.worker import process_event


@pytest.fixture
def sample_event():
    return IngestEvent(
        execution_id="exec-test-123",
        agent_id="test-bot",
        task="Answer questions",
        input={"query": "hello"},
        output={"response": "world"},
        token_count=150,
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
    mock.execute = MagicMock()
    mock.commit = MagicMock()
    return mock


def test_process_event_writes_to_s3(sample_event, mock_s3, mock_db_session):
    process_event(sample_event, s3_client=mock_s3, db_session=mock_db_session, org_id="org-1")
    mock_s3.put_object.assert_called_once()
    call_kwargs = mock_s3.put_object.call_args[1]
    assert call_kwargs["Bucket"] == "agentguard-traces"
    assert "exec-test-123" in call_kwargs["Key"]


def test_process_event_writes_to_db(sample_event, mock_s3, mock_db_session):
    process_event(sample_event, s3_client=mock_s3, db_session=mock_db_session, org_id="org-1")
    mock_db_session.execute.assert_called_once()
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
    call_args = mock_db_session.execute.call_args
    params = call_args[0][1]  # second positional arg is the params dict
    assert params["execution_id"] == "exec-test-123"
    assert params["agent_id"] == "test-bot"
    assert params["org_id"] == "org-1"
    assert params["latency_ms"] == 320.5
    assert params["token_count"] == 150
    assert "s3://agentguard-traces/" in params["trace_payload_ref"]
