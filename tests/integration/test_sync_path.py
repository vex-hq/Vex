"""Integration test for the synchronous verification path.

SDK (sync mode) → Sync Gateway → engine → response with confidence/action
→ event to Redis → verify data contracts for downstream services.

Tests the sync gateway end-to-end with mocked engine and Redis,
verifying that the response format and Redis event payloads satisfy
the contracts expected by the storage worker and alert service.
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

# The sync-gateway's ``app`` package must be importable.
_gw_path = str(Path(__file__).resolve().parent.parent.parent / "services" / "sync-gateway")
if _gw_path not in sys.path:
    sys.path.insert(0, _gw_path)

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from engine.models import CheckResult, VerificationResult


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.xadd = AsyncMock()
    r.aclose = AsyncMock()
    return r


@pytest.fixture
def gateway_app(mock_redis):
    from app.main import create_app
    application = create_app()
    application.state.redis = mock_redis
    return application


@pytest_asyncio.fixture
async def client(gateway_app):
    transport = ASGITransport(app=gateway_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_path_end_to_end(client, mock_redis):
    """Full sync path: verify → response + Redis events with correct data contracts."""
    mock_result = VerificationResult(
        confidence=0.85,
        action="pass",
        checks={
            "schema": CheckResult(check_type="schema", score=1.0, passed=True, details={}),
            "hallucination": CheckResult(
                check_type="hallucination", score=0.8, passed=True,
                details={"claims": ["Revenue is $1M"], "grounded": ["Revenue is $1M"], "ungrounded": []},
            ),
            "drift": CheckResult(
                check_type="drift", score=0.75, passed=True,
                details={"explanation": "Output is relevant to task"},
            ),
        },
    )

    with patch("app.routes.run_verification", new_callable=AsyncMock, return_value=mock_result):
        response = await client.post(
            "/v1/verify",
            json={
                "execution_id": "exec-sync-001",
                "agent_id": "report-gen",
                "task": "Generate financial report",
                "input": {"query": "Q4 report"},
                "output": {"revenue": 1000000},
                "ground_truth": {"revenue": 1000000},
                "schema_definition": {"type": "object", "required": ["revenue"]},
                "metadata": {
                    "thresholds": {"pass_threshold": 0.8, "flag_threshold": 0.5}
                },
            },
            headers={"X-AgentGuard-Key": "test-key"},
        )

    # Verify gateway response matches VerifyResponse contract
    assert response.status_code == 200
    data = response.json()
    assert data["execution_id"] == "exec-sync-001"
    assert data["confidence"] == 0.85
    assert data["action"] == "pass"
    assert data["output"] == {"revenue": 1000000}
    assert len(data["checks"]) == 3
    assert data["checks"]["schema"]["passed"] is True
    assert data["checks"]["hallucination"]["score"] == 0.8

    # Verify Redis events emitted
    assert mock_redis.xadd.call_count == 2
    call_args_list = mock_redis.xadd.call_args_list
    stream_names = [call[0][0] for call in call_args_list]
    assert "executions.verified" in stream_names
    assert "executions.raw" in stream_names

    # Verify verified event data contract (consumed by storage worker + alert service)
    for call in call_args_list:
        if call[0][0] == "executions.verified":
            verified_payload = json.loads(call[0][1]["data"])
            # Required fields for storage worker
            assert "execution_id" in verified_payload
            assert "agent_id" in verified_payload
            assert "confidence" in verified_payload
            assert "action" in verified_payload
            assert "checks" in verified_payload
            # checks must be valid JSON
            checks = json.loads(verified_payload["checks"])
            assert isinstance(checks, dict)

    # Verify raw event data contract (consumed by storage worker for S3/DB)
    for call in call_args_list:
        if call[0][0] == "executions.raw":
            raw_payload = json.loads(call[0][1]["data"])
            assert raw_payload["execution_id"] == "exec-sync-001"
            assert raw_payload["agent_id"] == "report-gen"
            assert "output" in raw_payload


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_path_block_triggers_correct_event(client, mock_redis):
    """Block action produces correct data for downstream alert service."""
    mock_result = VerificationResult(
        confidence=0.2,
        action="block",
        checks={
            "schema": CheckResult(check_type="schema", score=0.0, passed=False, details={"errors": ["missing revenue"]}),
            "hallucination": CheckResult(check_type="hallucination", score=0.3, passed=False, details={}),
            "drift": CheckResult(check_type="drift", score=0.1, passed=False, details={}),
        },
    )

    with patch("app.routes.run_verification", new_callable=AsyncMock, return_value=mock_result):
        response = await client.post(
            "/v1/verify",
            json={
                "execution_id": "exec-block-001",
                "agent_id": "unreliable-bot",
                "task": "Generate report",
                "input": "query",
                "output": {"wrong": "data"},
            },
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "block"
    assert data["confidence"] == 0.2

    # Verify the verified event for alert service has block action
    for call in mock_redis.xadd.call_args_list:
        if call[0][0] == "executions.verified":
            verified = json.loads(call[0][1]["data"])
            assert verified["action"] == "block"
            # Alert service will use this to determine severity=critical


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_path_timeout_produces_passthrough(client, mock_redis):
    """Timeout returns pass action, still emits Redis events."""
    import asyncio

    async def slow_verify(**kwargs):
        await asyncio.sleep(10)

    with patch("app.routes.run_verification", side_effect=slow_verify):
        response = await client.post(
            "/v1/verify",
            json={
                "execution_id": "exec-timeout-001",
                "agent_id": "slow-bot",
                "input": "hello",
                "output": "world",
            },
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "pass"
    assert data["confidence"] is None

    # Still emits Redis events (raw at minimum)
    assert mock_redis.xadd.call_count >= 1
