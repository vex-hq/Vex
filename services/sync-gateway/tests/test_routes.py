"""Tests for the sync gateway API routes."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth import verify_api_key, verify_ingest_key
from app.main import create_app
from engine.models import CheckResult, VerificationResult
from shared.auth import KeyInfo


def _fake_key_info() -> KeyInfo:
    """Return a stub KeyInfo for test auth bypass."""
    return KeyInfo(org_id="test-org", key_id="test-key", scopes=["verify", "ingest"])


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.xadd = AsyncMock()
    r.aclose = AsyncMock()
    return r


@pytest.fixture
def app(mock_redis):
    application = create_app()
    application.state.redis = mock_redis
    # Bypass auth for all test routes
    application.dependency_overrides[verify_api_key] = _fake_key_info
    application.dependency_overrides[verify_ingest_key] = _fake_key_info
    return application


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health_check(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_verify_returns_result(client, mock_redis):
    mock_result = VerificationResult(
        confidence=0.92,
        action="pass",
        checks={
            "schema": CheckResult(check_type="schema", score=1.0, passed=True),
            "hallucination": CheckResult(check_type="hallucination", score=0.9, passed=True),
            "drift": CheckResult(check_type="drift", score=0.85, passed=True),
        },
    )

    with patch("app.routes.run_verification", new_callable=AsyncMock, return_value=mock_result):
        response = await client.post(
            "/v1/verify",
            json={
                "agent_id": "test-bot",
                "input": "hello",
                "output": "world",
                "task": "greet user",
            },
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "pass"
    assert data["confidence"] == 0.92
    assert "schema" in data["checks"]
    assert "hallucination" in data["checks"]
    assert "drift" in data["checks"]


@pytest.mark.asyncio
async def test_verify_timeout_returns_passthrough(client, mock_redis):
    """When verification exceeds the 2s timeout, return pass-through."""

    async def slow_verify(**kwargs):
        await asyncio.sleep(10)

    with patch("app.routes.run_verification", side_effect=slow_verify):
        response = await client.post(
            "/v1/verify",
            json={
                "agent_id": "test-bot",
                "input": "hello",
                "output": "world",
            },
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "pass"
    assert data["confidence"] is None


@pytest.mark.asyncio
async def test_verify_emits_redis_events(client, mock_redis):
    mock_result = VerificationResult(
        confidence=0.5,
        action="flag",
        checks={
            "schema": CheckResult(check_type="schema", score=1.0, passed=True),
        },
    )

    with patch("app.routes.run_verification", new_callable=AsyncMock, return_value=mock_result):
        response = await client.post(
            "/v1/verify",
            json={
                "agent_id": "test-bot",
                "input": "hello",
                "output": "world",
            },
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert response.status_code == 200
    # Should emit to both verified and raw streams
    assert mock_redis.xadd.call_count == 2

    # Check stream names
    call_args_list = mock_redis.xadd.call_args_list
    stream_names = [call[0][0] for call in call_args_list]
    assert "executions.verified" in stream_names
    assert "executions.raw" in stream_names


@pytest.mark.asyncio
async def test_verify_missing_api_key(mock_redis):
    """Auth is NOT bypassed here — missing header should return 401."""
    application = create_app()
    application.state.redis = mock_redis
    # No dependency_overrides → real auth runs
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.post(
            "/v1/verify",
            json={
                "agent_id": "test-bot",
                "input": "hello",
                "output": "world",
            },
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_verify_forwards_conversation_history(client, mock_redis):
    """Conversation history from the request should be forwarded to the engine."""
    mock_result = VerificationResult(
        confidence=0.9,
        action="pass",
        checks={
            "schema": CheckResult(check_type="schema", score=1.0, passed=True),
            "hallucination": CheckResult(check_type="hallucination", score=0.9, passed=True),
            "drift": CheckResult(check_type="drift", score=0.85, passed=True),
            "coherence": CheckResult(check_type="coherence", score=1.0, passed=True),
        },
    )

    with patch("app.routes.run_verification", new_callable=AsyncMock, return_value=mock_result) as mock_verify:
        response = await client.post(
            "/v1/verify",
            json={
                "agent_id": "test-bot",
                "input": "What is profit?",
                "output": "Profit is $800M.",
                "task": "Financial summary",
                "ground_truth": {"profit": "$800M"},
                "conversation_history": [
                    {
                        "sequence_number": 0,
                        "input": "What is revenue?",
                        "output": "Revenue is $5.2B.",
                        "task": "Financial summary",
                    }
                ],
            },
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert response.status_code == 200
    # Verify conversation_history was forwarded to the engine
    call_kwargs = mock_verify.call_args.kwargs
    assert "conversation_history" in call_kwargs
    assert call_kwargs["conversation_history"] is not None
    assert len(call_kwargs["conversation_history"]) == 1
    assert call_kwargs["conversation_history"][0].sequence_number == 0


@pytest.mark.asyncio
async def test_verify_with_threshold_config(client, mock_redis):
    mock_result = VerificationResult(
        confidence=0.7,
        action="flag",
        checks={},
    )

    with patch("app.routes.run_verification", new_callable=AsyncMock, return_value=mock_result) as mock_verify:
        response = await client.post(
            "/v1/verify",
            json={
                "agent_id": "test-bot",
                "input": "hello",
                "output": "world",
                "metadata": {
                    "thresholds": {
                        "pass_threshold": 0.9,
                        "flag_threshold": 0.6,
                    }
                },
            },
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert response.status_code == 200
    # Verify config was passed with custom thresholds
    call_kwargs = mock_verify.call_args
    config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
    assert config.pass_threshold == 0.9
    assert config.flag_threshold == 0.6


# --- Correction cascade tests ---


@pytest.mark.asyncio
async def test_verify_no_correction_unchanged(client, mock_redis):
    """When correction=none (default), behavior is identical to before."""
    mock_result = VerificationResult(
        confidence=0.4,
        action="block",
        checks={
            "schema": CheckResult(check_type="schema", score=0.0, passed=False),
        },
    )

    with patch("app.routes.run_verification", new_callable=AsyncMock, return_value=mock_result):
        response = await client.post(
            "/v1/verify",
            json={
                "agent_id": "test-bot",
                "input": "hello",
                "output": "world",
                "metadata": {"correction": "none"},
            },
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "block"
    assert data["corrected"] is False


@pytest.mark.asyncio
async def test_verify_correction_layer1_succeeds(client, mock_redis):
    """Correction cascade: Layer 1 succeeds → returns corrected output."""
    from engine.models import CorrectionAttempt

    failed_result = VerificationResult(
        confidence=0.6, action="flag",
        checks={
            "schema": CheckResult(check_type="schema", score=0.0, passed=False, details={"errors": ["missing field"]}),
            "hallucination": CheckResult(check_type="hallucination", score=1.0, passed=True),
            "drift": CheckResult(check_type="drift", score=0.9, passed=True),
        },
    )
    pass_result = VerificationResult(
        confidence=0.95, action="pass",
        checks={
            "schema": CheckResult(check_type="schema", score=1.0, passed=True),
            "hallucination": CheckResult(check_type="hallucination", score=1.0, passed=True),
            "drift": CheckResult(check_type="drift", score=0.9, passed=True),
        },
    )
    mock_correction = CorrectionAttempt(
        layer=1, layer_name="repair", input_action="flag",
        input_confidence=0.6, corrected_output='{"revenue": 5200000}',
        model_used="gpt-4o-mini", latency_ms=300.0, success=True,
    )

    with patch("app.routes.run_verification", new_callable=AsyncMock, side_effect=[failed_result, pass_result]), \
         patch("app.routes.run_correction", new_callable=AsyncMock, return_value=mock_correction):
        response = await client.post(
            "/v1/verify",
            json={"agent_id": "test-bot", "input": "hello", "output": '{"revnue": 5200000}',
                  "metadata": {"correction": "cascade"}},
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "pass"
    assert data["corrected"] is True
    assert data["confidence"] == 0.95


@pytest.mark.asyncio
async def test_verify_correction_escalates_l1_to_l2(client, mock_redis):
    """Layer 1 fails, Layer 2 succeeds → 2 attempts, corrected."""
    from engine.models import CorrectionAttempt

    failed_result = VerificationResult(confidence=0.55, action="flag", checks={
        "schema": CheckResult(check_type="schema", score=0.0, passed=False),
        "hallucination": CheckResult(check_type="hallucination", score=1.0, passed=True),
    })
    still_failed = VerificationResult(confidence=0.45, action="block", checks={
        "schema": CheckResult(check_type="schema", score=0.0, passed=False),
    })
    pass_result = VerificationResult(confidence=0.9, action="pass", checks={
        "schema": CheckResult(check_type="schema", score=1.0, passed=True),
    })

    l1_attempt = CorrectionAttempt(layer=1, layer_name="repair", input_action="flag",
        corrected_output="still broken", model_used="gpt-4o-mini", latency_ms=200.0, success=True)
    l2_attempt = CorrectionAttempt(layer=2, layer_name="constrained_regen", input_action="block",
        corrected_output="properly fixed", model_used="gpt-4o", latency_ms=1200.0, success=True)

    with patch("app.routes.run_verification", new_callable=AsyncMock,
               side_effect=[failed_result, still_failed, pass_result]), \
         patch("app.routes.run_correction", new_callable=AsyncMock,
               side_effect=[l1_attempt, l2_attempt]):
        response = await client.post(
            "/v1/verify",
            json={"agent_id": "test-bot", "input": "hello", "output": "broken",
                  "metadata": {"correction": "cascade"}},
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "pass"
    assert data["corrected"] is True


@pytest.mark.asyncio
async def test_verify_correction_all_fail_blocks(client, mock_redis):
    """All correction layers fail → block."""
    from engine.models import CorrectionAttempt

    failed = VerificationResult(confidence=0.4, action="block", checks={
        "hallucination": CheckResult(check_type="hallucination", score=0.1, passed=False),
    })
    still_failed = VerificationResult(confidence=0.35, action="block", checks={
        "hallucination": CheckResult(check_type="hallucination", score=0.2, passed=False),
    })

    attempt = CorrectionAttempt(layer=2, layer_name="constrained_regen", input_action="block",
        corrected_output="still bad", model_used="gpt-4o", latency_ms=1000.0, success=True)

    with patch("app.routes.run_verification", new_callable=AsyncMock,
               side_effect=[failed, still_failed, still_failed]), \
         patch("app.routes.run_correction", new_callable=AsyncMock, return_value=attempt):
        response = await client.post(
            "/v1/verify",
            json={"agent_id": "test-bot", "input": "hello", "output": "bad output",
                  "metadata": {"correction": "cascade"}},
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "block"
    assert data["corrected"] is False


@pytest.mark.asyncio
async def test_verify_correction_timeout_passthrough(client, mock_redis):
    """10s timeout during correction → pass-through."""
    async def slow_verify(**kwargs):
        await asyncio.sleep(15)

    with patch("app.routes.run_verification", side_effect=slow_verify):
        response = await client.post(
            "/v1/verify",
            json={"agent_id": "test-bot", "input": "hello", "output": "world",
                  "metadata": {"correction": "cascade"}},
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "pass"
    assert data["corrected"] is False


@pytest.mark.asyncio
async def test_verify_correction_uses_original_output(client, mock_redis):
    """Correction always uses original output, not previous correction's output."""
    from engine.models import CorrectionAttempt

    original_output = "original broken output"
    failed = VerificationResult(confidence=0.4, action="block", checks={})
    still_failed = VerificationResult(confidence=0.4, action="block", checks={})
    pass_result = VerificationResult(confidence=0.9, action="pass", checks={})

    correction_calls = []

    async def mock_correct(**kwargs):
        correction_calls.append(kwargs.get("output"))
        return CorrectionAttempt(
            layer=kwargs.get("layer", 2), layer_name="constrained_regen",
            input_action="block", corrected_output="corrected v" + str(len(correction_calls)),
            model_used="gpt-4o", latency_ms=500.0, success=True,
        )

    with patch("app.routes.run_verification", new_callable=AsyncMock,
               side_effect=[failed, still_failed, pass_result]), \
         patch("app.routes.run_correction", side_effect=mock_correct):
        response = await client.post(
            "/v1/verify",
            json={"agent_id": "test-bot", "input": "hello", "output": original_output,
                  "metadata": {"correction": "cascade"}},
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert all(c == original_output for c in correction_calls)


@pytest.mark.asyncio
async def test_verify_correction_emits_redis_with_correction_metadata(client, mock_redis):
    """Redis events should include correction metadata."""
    from engine.models import CorrectionAttempt

    failed = VerificationResult(confidence=0.6, action="flag", checks={
        "schema": CheckResult(check_type="schema", score=0.0, passed=False),
    })
    pass_result = VerificationResult(confidence=0.95, action="pass", checks={
        "schema": CheckResult(check_type="schema", score=1.0, passed=True),
    })
    attempt = CorrectionAttempt(layer=1, layer_name="repair", input_action="flag",
        corrected_output="fixed", model_used="gpt-4o-mini", latency_ms=300.0, success=True)

    with patch("app.routes.run_verification", new_callable=AsyncMock,
               side_effect=[failed, pass_result]), \
         patch("app.routes.run_correction", new_callable=AsyncMock, return_value=attempt):
        response = await client.post(
            "/v1/verify",
            json={"agent_id": "test-bot", "input": "hello", "output": "broken",
                  "metadata": {"correction": "cascade"}},
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert response.status_code == 200
    assert mock_redis.xadd.call_count >= 2
    verified_call = None
    for call in mock_redis.xadd.call_args_list:
        if call[0][0] == "executions.verified":
            verified_call = call
            break
    assert verified_call is not None
    data_str = verified_call[0][1]["data"]
    verified_data = json.loads(data_str)
    assert verified_data["corrected"] == "True"


@pytest.mark.asyncio
async def test_verify_pass_skips_correction(client, mock_redis):
    """When initial verification passes, correction is NOT triggered."""
    pass_result = VerificationResult(
        confidence=0.95, action="pass", checks={
            "schema": CheckResult(check_type="schema", score=1.0, passed=True),
        },
    )

    with patch("app.routes.run_verification", new_callable=AsyncMock, return_value=pass_result) as mock_verify:
        response = await client.post(
            "/v1/verify",
            json={"agent_id": "test-bot", "input": "hello", "output": "good output",
                  "metadata": {"correction": "cascade"}},
            headers={"X-AgentGuard-Key": "test-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "pass"
    assert data["corrected"] is False
    assert mock_verify.call_count == 1


# --- Ingestion endpoint tests ---


@pytest.mark.asyncio
async def test_ingest_single_event(client, mock_redis):
    event = {
        "agent_id": "test-bot",
        "input": {"query": "hello"},
        "output": {"response": "world"},
    }
    response = await client.post(
        "/v1/ingest",
        json=event,
        headers={"X-AgentGuard-Key": "test-key"},
    )
    assert response.status_code == 202
    data = response.json()
    assert data["accepted"] == 1
    assert "execution_id" in data
    mock_redis.xadd.assert_called_once()


@pytest.mark.asyncio
async def test_ingest_batch(client, mock_redis):
    events = {
        "events": [
            {"agent_id": "bot-1", "input": {}, "output": {}},
            {"agent_id": "bot-2", "input": {}, "output": {}},
            {"agent_id": "bot-3", "input": {}, "output": {}},
        ]
    }
    response = await client.post(
        "/v1/ingest/batch",
        json=events,
        headers={"X-AgentGuard-Key": "test-key"},
    )
    assert response.status_code == 202
    data = response.json()
    assert data["accepted"] == 3
    assert len(data["execution_ids"]) == 3
    assert mock_redis.xadd.call_count == 3


@pytest.mark.asyncio
async def test_ingest_rejects_invalid_payload(client):
    response = await client.post(
        "/v1/ingest",
        json={"bad": "data"},
        headers={"X-AgentGuard-Key": "test-key"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_batch_rejects_over_50_events(client):
    events = {"events": [{"agent_id": f"bot-{i}", "input": {}, "output": {}} for i in range(51)]}
    response = await client.post(
        "/v1/ingest/batch",
        json=events,
        headers={"X-AgentGuard-Key": "test-key"},
    )
    assert response.status_code == 422
