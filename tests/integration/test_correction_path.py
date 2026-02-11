"""Integration tests for the correction cascade path.

Tests the full flow: SDK config -> Gateway -> Engine verify -> Engine correct
-> re-verify -> response with correction metadata -> Redis events.
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Add service paths
_root = Path(__file__).resolve().parent.parent.parent
_gw_path = str(_root / "services" / "sync-gateway")
if _gw_path not in sys.path:
    sys.path.insert(0, _gw_path)

from engine.models import CheckResult, CorrectionAttempt, VerificationResult


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
async def test_correction_succeeds_layer1(client, mock_redis):
    """Full integration: verify fails -> correct L1 -> re-verify passes -> corrected response."""
    failed = VerificationResult(confidence=0.6, action="flag", checks={
        "schema": CheckResult(check_type="schema", score=0.0, passed=False,
                              details={"errors": ["missing field"]}),
        "hallucination": CheckResult(check_type="hallucination", score=1.0, passed=True),
    })
    passed = VerificationResult(confidence=0.95, action="pass", checks={
        "schema": CheckResult(check_type="schema", score=1.0, passed=True),
        "hallucination": CheckResult(check_type="hallucination", score=1.0, passed=True),
    })
    attempt = CorrectionAttempt(
        layer=1, layer_name="repair", input_action="flag", input_confidence=0.6,
        corrected_output='{"revenue": 5200000}',
        model_used="gpt-4o-mini", latency_ms=300.0, success=True,
    )

    with patch("app.routes.run_verification", new_callable=AsyncMock, side_effect=[failed, passed]), \
         patch("app.routes.run_correction", new_callable=AsyncMock, return_value=attempt):
        response = await client.post(
            "/v1/verify",
            json={
                "agent_id": "test-bot",
                "input": "query",
                "output": '{"revnue": 5200000}',
                "task": "Generate report",
                "metadata": {"correction": "cascade"},
            },
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "pass"
    assert data["corrected"] is True
    assert data["confidence"] == 0.95

    # Verify Redis events emitted
    assert mock_redis.xadd.call_count >= 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_correction_escalates_l1_l2(client, mock_redis):
    """L1 fails -> L2 succeeds -> corrected with 2 attempts."""
    failed = VerificationResult(confidence=0.55, action="flag", checks={
        "schema": CheckResult(check_type="schema", score=0.0, passed=False),
    })
    still_failed = VerificationResult(confidence=0.4, action="block", checks={
        "schema": CheckResult(check_type="schema", score=0.0, passed=False),
    })
    passed = VerificationResult(confidence=0.9, action="pass", checks={
        "schema": CheckResult(check_type="schema", score=1.0, passed=True),
    })
    l1 = CorrectionAttempt(layer=1, layer_name="repair", input_action="flag",
                           corrected_output="bad", model_used="gpt-4o-mini",
                           latency_ms=200.0, success=True)
    l2 = CorrectionAttempt(layer=2, layer_name="constrained_regen", input_action="block",
                           corrected_output="good", model_used="gpt-4o",
                           latency_ms=1200.0, success=True)

    with patch("app.routes.run_verification", new_callable=AsyncMock,
               side_effect=[failed, still_failed, passed]), \
         patch("app.routes.run_correction", new_callable=AsyncMock, side_effect=[l1, l2]):
        response = await client.post(
            "/v1/verify",
            json={"agent_id": "bot", "input": "q", "output": "bad",
                  "metadata": {"correction": "cascade"}},
            headers={"X-AgentGuard-Key": "test-key"},
        )

    data = response.json()
    assert data["action"] == "pass"
    assert data["corrected"] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_correction_fails_all_layers(client, mock_redis):
    """All correction attempts fail -> block."""
    failed = VerificationResult(confidence=0.3, action="block", checks={
        "hallucination": CheckResult(check_type="hallucination", score=0.1, passed=False),
    })
    attempt = CorrectionAttempt(layer=2, layer_name="constrained_regen",
                                input_action="block", corrected_output="still bad",
                                model_used="gpt-4o", latency_ms=1000.0, success=True)

    with patch("app.routes.run_verification", new_callable=AsyncMock, return_value=failed), \
         patch("app.routes.run_correction", new_callable=AsyncMock, return_value=attempt):
        response = await client.post(
            "/v1/verify",
            json={"agent_id": "bot", "input": "q", "output": "bad",
                  "metadata": {"correction": "cascade"}},
            headers={"X-AgentGuard-Key": "test-key"},
        )

    data = response.json()
    assert data["action"] == "block"
    assert data["corrected"] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_correction_regression(client, mock_redis):
    """correction=none -> identical to Phase 2 behavior."""
    result = VerificationResult(confidence=0.6, action="flag", checks={
        "hallucination": CheckResult(check_type="hallucination", score=0.6, passed=True),
    })

    with patch("app.routes.run_verification", new_callable=AsyncMock, return_value=result):
        response = await client.post(
            "/v1/verify",
            json={"agent_id": "bot", "input": "q", "output": "output",
                  "metadata": {"correction": "none"}},
            headers={"X-AgentGuard-Key": "test-key"},
        )

    data = response.json()
    assert data["action"] == "flag"
    assert data["corrected"] is False
