"""Integration test for the asynchronous verification path.

SDK (async mode) → Ingestion API → executions.raw → async worker →
executions.verified → storage worker writes check_results →
alert service fires webhook (mock) → verify DB state + webhook received.

Tests are structured to verify the data flow between services without
requiring live Redis/PostgreSQL connections. Each service's processing
function is called directly with the output of the previous step.

Worker modules from different services are loaded via importlib helpers
in conftest.py (exposed as session-scoped fixtures) to avoid ``app``
namespace collisions.

Mark with @pytest.mark.integration.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from engine.models import CheckResult, VerificationResult
from shared.models import IngestEvent


@pytest.mark.integration
@pytest.mark.asyncio
async def test_async_verification_full_path(async_worker_module, storage_worker_module):
    """Test the full async path through all services."""

    # 1. Create an ingest event (mimics SDK async mode sending to ingestion API)
    event = IngestEvent(
        execution_id="exec-async-001",
        agent_id="data-enricher",
        task="Enrich customer data",
        input={"customer_id": "cust-123"},
        output={"customer_id": "cust-123", "name": "ACME Corp", "revenue": 5000000},
        ground_truth={"customer_id": "cust-123", "name": "ACME Corp", "revenue": 5000000},
        schema_definition={
            "type": "object",
            "required": ["customer_id", "name", "revenue"],
        },
        token_count=250,
        cost_estimate=0.0005,
        latency_ms=450.0,
    )

    # 2. Simulate async worker processing the event
    mock_verification = VerificationResult(
        confidence=0.9,
        action="pass",
        checks={
            "schema": CheckResult(check_type="schema", score=1.0, passed=True, details={}),
            "hallucination": CheckResult(
                check_type="hallucination", score=0.85, passed=True,
                details={"claims": ["ACME Corp revenue is $5M"], "grounded": ["ACME Corp revenue is $5M"], "ungrounded": []},
            ),
            "drift": CheckResult(
                check_type="drift", score=0.9, passed=True,
                details={"explanation": "Output enriches customer data as requested"},
            ),
        },
    )

    with patch.object(async_worker_module, "verify", new_callable=AsyncMock, return_value=mock_verification):
        verified_dict = await async_worker_module.process_event(event)

    assert verified_dict["execution_id"] == "exec-async-001"
    assert verified_dict["action"] == "pass"
    assert verified_dict["confidence"] == "0.9"
    checks = json.loads(verified_dict["checks"])
    assert len(checks) == 3

    # 3. Simulate storage worker processing the verified event
    mock_db = MagicMock()
    mock_db.execute = MagicMock()
    mock_db.commit = MagicMock()

    stored = storage_worker_module.process_verified_event(verified_dict, mock_db)
    assert stored["execution_id"] == "exec-async-001"
    assert stored["checks_stored"] == 3
    assert stored["confidence"] == 0.9

    # Verify 3 INSERT check_results + 1 UPDATE execution = 4 calls
    assert mock_db.execute.call_count == 4
    assert mock_db.commit.call_count == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_async_path_flag_triggers_alert(async_worker_module, alert_worker_module):
    """Test that flag action triggers alert service processing."""

    event = IngestEvent(
        execution_id="exec-async-flag",
        agent_id="risky-bot",
        task="Generate financial advice",
        input={"query": "investment tips"},
        output="Buy crypto now! Guaranteed returns!",
        ground_truth={"disclaimer": "Not financial advice"},
    )

    mock_verification = VerificationResult(
        confidence=0.4,
        action="block",
        checks={
            "schema": CheckResult(check_type="schema", score=1.0, passed=True, details={"skipped": True}),
            "hallucination": CheckResult(
                check_type="hallucination", score=0.2, passed=False,
                details={"claims": ["Guaranteed returns"], "ungrounded": ["Guaranteed returns"]},
            ),
            "drift": CheckResult(
                check_type="drift", score=0.3, passed=False,
                details={"explanation": "Output makes risky claims not aligned with task"},
            ),
        },
    )

    with patch.object(async_worker_module, "verify", new_callable=AsyncMock, return_value=mock_verification):
        verified_dict = await async_worker_module.process_event(event)

    assert verified_dict["action"] == "block"

    # 4. Simulate alert service processing
    mock_db = MagicMock()
    mock_db.execute = MagicMock()
    mock_db.commit = MagicMock()

    with patch.object(alert_worker_module, "get_webhook_url", return_value="https://hooks.example.com/alerts"), \
         patch.object(alert_worker_module, "deliver", new_callable=AsyncMock, return_value=(True, 200)):
        alert_result = await alert_worker_module.process_verified_event(verified_dict, mock_db)

    assert alert_result is not None
    assert alert_result["action"] == "block"
    assert alert_result["delivered"] is True

    # Verify alert was written to DB
    mock_db.execute.assert_called_once()
    mock_db.commit.assert_called_once()

    params = mock_db.execute.call_args[0][1]
    assert params["severity"] == "critical"  # block → critical
    assert params["alert_type"] == "verification_block"
    assert params["webhook_url"] == "https://hooks.example.com/alerts"
    assert params["response_status"] == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_async_path_pass_skips_alert(alert_worker_module):
    """Pass events should not trigger alerts."""

    verified_dict = {
        "execution_id": "exec-pass-001",
        "agent_id": "good-bot",
        "confidence": "0.95",
        "action": "pass",
        "checks": "{}",
    }

    mock_db = MagicMock()
    result = await alert_worker_module.process_verified_event(verified_dict, mock_db)

    assert result is None
    mock_db.execute.assert_not_called()
