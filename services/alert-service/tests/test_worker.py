"""Tests for the alert service worker."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker import process_verified_event


@pytest.fixture
def mock_db_session():
    mock = MagicMock()
    mock.execute = MagicMock()
    mock.commit = MagicMock()
    return mock


@pytest.fixture
def flag_event():
    return {
        "execution_id": "exec-789",
        "agent_id": "test-bot",
        "confidence": "0.6",
        "action": "flag",
        "checks": json.dumps({
            "schema": {"check_type": "schema", "score": 0.0, "passed": False, "details": {}},
            "hallucination": {"check_type": "hallucination", "score": 0.9, "passed": True, "details": {}},
        }),
    }


@pytest.fixture
def block_event():
    return {
        "execution_id": "exec-block-001",
        "agent_id": "critical-bot",
        "confidence": "0.2",
        "action": "block",
        "checks": json.dumps({
            "schema": {"check_type": "schema", "score": 0.0, "passed": False, "details": {}},
            "hallucination": {"check_type": "hallucination", "score": 0.3, "passed": False, "details": {}},
        }),
    }


@pytest.fixture
def pass_event():
    return {
        "execution_id": "exec-pass-001",
        "agent_id": "good-bot",
        "confidence": "0.95",
        "action": "pass",
        "checks": "{}",
    }


@pytest.mark.asyncio
async def test_skip_pass_events(pass_event, mock_db_session):
    result = await process_verified_event(pass_event, mock_db_session)
    assert result is None
    mock_db_session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_flag_event_creates_alert(flag_event, mock_db_session):
    with patch("app.worker.get_webhook_url", return_value=None):
        result = await process_verified_event(flag_event, mock_db_session)

    assert result is not None
    assert result["execution_id"] == "exec-789"
    assert result["action"] == "flag"
    assert result["delivered"] is False

    mock_db_session.execute.assert_called_once()
    mock_db_session.commit.assert_called_once()

    # Verify alert params
    call_args = mock_db_session.execute.call_args
    params = call_args[0][1]
    assert params["severity"] == "high"
    assert params["alert_type"] == "verification_flag"


@pytest.mark.asyncio
async def test_block_event_creates_critical_alert(block_event, mock_db_session):
    with patch("app.worker.get_webhook_url", return_value=None):
        result = await process_verified_event(block_event, mock_db_session)

    assert result is not None
    assert result["action"] == "block"

    call_args = mock_db_session.execute.call_args
    params = call_args[0][1]
    assert params["severity"] == "critical"
    assert params["alert_type"] == "verification_block"


@pytest.mark.asyncio
async def test_webhook_delivery_on_flag(flag_event, mock_db_session):
    with patch("app.worker.get_webhook_url", return_value="https://hooks.example.com/alert"), \
         patch("app.worker.deliver", new_callable=AsyncMock, return_value=(True, 200)):
        result = await process_verified_event(flag_event, mock_db_session)

    assert result["delivered"] is True

    call_args = mock_db_session.execute.call_args
    params = call_args[0][1]
    assert params["delivered"] is True
    assert params["webhook_url"] == "https://hooks.example.com/alert"
    assert params["response_status"] == 200


@pytest.mark.asyncio
async def test_webhook_delivery_failure(flag_event, mock_db_session):
    with patch("app.worker.get_webhook_url", return_value="https://hooks.example.com/alert"), \
         patch("app.worker.deliver", new_callable=AsyncMock, return_value=(False, 500)):
        result = await process_verified_event(flag_event, mock_db_session)

    assert result["delivered"] is False

    call_args = mock_db_session.execute.call_args
    params = call_args[0][1]
    assert params["delivered"] is False
    assert params["delivery_attempts"] == 3
    assert params["response_status"] == 500
