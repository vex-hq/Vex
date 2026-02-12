"""Integration test for the API key lifecycle.

Tests the full flow:
1. Valid key → request succeeds with org_id resolved.
2. Wrong scope → 403 Forbidden.
3. Revoked key → 401 Unauthorized.
4. Expired key → 401 Unauthorized.
5. Rate-limited key → 429 Too Many Requests.
6. Missing key → 401 Unauthorized.

Uses the sync gateway with a mocked ``KeyValidator`` to simulate
database state transitions without requiring a live database.
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from engine.models import CheckResult, VerificationResult
from shared.auth import AuthError, KeyInfo

# Ensure the gateway app is importable
_gw_path = str(Path(__file__).resolve().parent.parent.parent / "services" / "sync-gateway")
if _gw_path not in sys.path:
    sys.path.insert(0, _gw_path)


def _make_mock_validator(key_info=None, error=None):
    """Create a mock KeyValidator that returns *key_info* or raises *error*."""
    validator = MagicMock()
    validator.close = MagicMock()
    validator.flush_usage = MagicMock()

    if error:
        validator.validate = MagicMock(side_effect=error)
    else:
        validator.validate = MagicMock(return_value=key_info)

    return validator


def _passing_verification():
    """A simple passing verification result for gateway to return."""
    return VerificationResult(
        confidence=0.9,
        action="pass",
        checks={
            "schema": CheckResult(check_type="schema", score=1.0, passed=True, details={}),
            "hallucination": CheckResult(
                check_type="hallucination", score=0.85, passed=True, details={},
            ),
            "drift": CheckResult(
                check_type="drift", score=0.85, passed=True, details={},
            ),
        },
    )


_VERIFY_PAYLOAD = {
    "execution_id": "exec-key-test-001",
    "agent_id": "test-agent",
    "task": "Generate report",
    "input": "some input",
    "output": "some output",
}


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.xadd = AsyncMock()
    r.aclose = AsyncMock()
    return r


@pytest_asyncio.fixture
async def make_client(mock_redis):
    """Factory fixture: returns an async client with a given validator mock."""

    async def _make(validator_mock):
        from app.main import create_app

        application = create_app()
        application.state.redis = mock_redis

        with patch("app.auth.get_validator", return_value=validator_mock):
            transport = ASGITransport(app=application)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                yield c

    return _make


# ---------------------------------------------------------------------------
# Test helpers — we need a simpler fixture approach since the validator
# is called within the dependency, not once at startup.
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_valid_key_allows_request(client, mock_redis):
    """A valid key with the 'verify' scope passes auth and reaches the engine."""
    valid_key_info = KeyInfo(org_id="acme-corp", key_id="key-001", scopes=["verify", "read"])
    mock_validator = _make_mock_validator(key_info=valid_key_info)

    with (
        patch("app.auth.get_validator", return_value=mock_validator),
        patch("app.routes.run_verification", new_callable=AsyncMock, return_value=_passing_verification()),
    ):
        response = await client.post(
            "/v1/verify",
            json=_VERIFY_PAYLOAD,
            headers={"X-AgentGuard-Key": "ag_live_validKey12345678901234567890"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["confidence"] == 0.9
    assert data["action"] == "pass"
    mock_validator.validate.assert_called_once_with("ag_live_validKey12345678901234567890")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_missing_key_returns_401(client):
    """A request without the X-AgentGuard-Key header is rejected."""
    response = await client.post(
        "/v1/verify",
        json=_VERIFY_PAYLOAD,
    )

    assert response.status_code == 401
    assert "Missing X-AgentGuard-Key" in response.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_invalid_key_returns_401(client):
    """An unknown key is rejected with 401."""
    mock_validator = _make_mock_validator(
        error=AuthError(status_code=401, detail="Invalid API key"),
    )

    with patch("app.auth.get_validator", return_value=mock_validator):
        response = await client.post(
            "/v1/verify",
            json=_VERIFY_PAYLOAD,
            headers={"X-AgentGuard-Key": "ag_live_badKeyXXXXXXXXXXXXXXXXXXXXXXX"},
        )

    assert response.status_code == 401
    assert "Invalid API key" in response.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_revoked_key_returns_401(client):
    """A key that was valid but is now revoked is rejected."""
    mock_validator = _make_mock_validator(
        error=AuthError(status_code=401, detail="API key has been revoked"),
    )

    with patch("app.auth.get_validator", return_value=mock_validator):
        response = await client.post(
            "/v1/verify",
            json=_VERIFY_PAYLOAD,
            headers={"X-AgentGuard-Key": "ag_live_revokedKey890123456789012345"},
        )

    assert response.status_code == 401
    assert "revoked" in response.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_expired_key_returns_401(client):
    """An expired key is rejected."""
    mock_validator = _make_mock_validator(
        error=AuthError(status_code=401, detail="API key has expired"),
    )

    with patch("app.auth.get_validator", return_value=mock_validator):
        response = await client.post(
            "/v1/verify",
            json=_VERIFY_PAYLOAD,
            headers={"X-AgentGuard-Key": "ag_live_expiredKey90123456789012345"},
        )

    assert response.status_code == 401
    assert "expired" in response.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_wrong_scope_returns_403(client):
    """A key without the 'verify' scope is rejected with 403."""
    mock_validator = _make_mock_validator(
        error=AuthError(status_code=403, detail="API key missing required scope: verify"),
    )

    with patch("app.auth.get_validator", return_value=mock_validator):
        response = await client.post(
            "/v1/verify",
            json=_VERIFY_PAYLOAD,
            headers={"X-AgentGuard-Key": "ag_live_ingestOnlyKey23456789012345"},
        )

    assert response.status_code == 403
    assert "scope" in response.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rate_limited_key_returns_429(client):
    """A key that exceeds its rate limit is rejected with 429 + Retry-After."""
    mock_validator = _make_mock_validator(
        error=AuthError(
            status_code=429,
            detail="Rate limit exceeded",
            retry_after_seconds=12,
        ),
    )

    with patch("app.auth.get_validator", return_value=mock_validator):
        response = await client.post(
            "/v1/verify",
            json=_VERIFY_PAYLOAD,
            headers={"X-AgentGuard-Key": "ag_live_hotKey678901234567890123456"},
        )

    assert response.status_code == 429
    assert "Rate limit" in response.json()["detail"]
    assert response.headers.get("retry-after") == "12"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_key_lifecycle_valid_then_revoked(client, mock_redis):
    """Simulates the full lifecycle: valid key works, then revocation blocks it.

    This is the closest to a real end-to-end test without a live database.
    The mock validator's behavior changes between the two calls to simulate
    key revocation.
    """
    valid_key = "ag_live_lifecycleKey890123456789012"

    # --- Phase 1: Key is valid ---
    valid_info = KeyInfo(org_id="acme-corp", key_id="key-lc-001", scopes=["verify"])
    mock_validator = _make_mock_validator(key_info=valid_info)

    with (
        patch("app.auth.get_validator", return_value=mock_validator),
        patch("app.routes.run_verification", new_callable=AsyncMock, return_value=_passing_verification()),
    ):
        resp1 = await client.post(
            "/v1/verify",
            json={**_VERIFY_PAYLOAD, "execution_id": "exec-lc-001"},
            headers={"X-AgentGuard-Key": valid_key},
        )

    assert resp1.status_code == 200
    assert resp1.json()["action"] == "pass"

    # --- Phase 2: Key is revoked (simulates DB update + cache expiry) ---
    revoked_validator = _make_mock_validator(
        error=AuthError(status_code=401, detail="API key has been revoked"),
    )

    with patch("app.auth.get_validator", return_value=revoked_validator):
        resp2 = await client.post(
            "/v1/verify",
            json={**_VERIFY_PAYLOAD, "execution_id": "exec-lc-002"},
            headers={"X-AgentGuard-Key": valid_key},
        )

    assert resp2.status_code == 401
    assert "revoked" in resp2.json()["detail"]
