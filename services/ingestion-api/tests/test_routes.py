from unittest.mock import AsyncMock


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_ingest_single_event(client, mock_redis):
    event = {
        "agent_id": "test-bot",
        "input": {"query": "hello"},
        "output": {"response": "world"},
    }
    response = client.post(
        "/v1/ingest",
        json=event,
        headers={"X-Vex-Key": "ag_test_key"},
    )
    assert response.status_code == 202
    assert "execution_id" in response.json()
    mock_redis.xadd.assert_called_once()


def test_ingest_batch(client, mock_redis):
    events = {
        "events": [
            {"agent_id": "bot-1", "input": {}, "output": {}},
            {"agent_id": "bot-2", "input": {}, "output": {}},
            {"agent_id": "bot-3", "input": {}, "output": {}},
        ]
    }
    response = client.post(
        "/v1/ingest/batch",
        json=events,
        headers={"X-Vex-Key": "ag_test_key"},
    )
    assert response.status_code == 202
    data = response.json()
    assert data["accepted"] == 3
    assert len(data["execution_ids"]) == 3
    assert mock_redis.xadd.call_count == 3


def test_ingest_rejects_missing_api_key(mock_redis):
    """Auth is NOT bypassed here — missing header should return 401."""
    from app.main import create_app
    from fastapi.testclient import TestClient

    app = create_app()
    app.state.redis = mock_redis
    # No dependency_overrides → real auth runs
    client_no_auth = TestClient(app)
    response = client_no_auth.post("/v1/ingest", json={"agent_id": "x", "input": {}, "output": {}})
    assert response.status_code == 401


def test_ingest_rejects_invalid_payload(client):
    response = client.post(
        "/v1/ingest",
        json={"bad": "data"},
        headers={"X-Vex-Key": "ag_test_key"},
    )
    assert response.status_code == 422


def test_batch_rejects_over_50_events(client):
    events = {"events": [{"agent_id": f"bot-{i}", "input": {}, "output": {}} for i in range(51)]}
    response = client.post(
        "/v1/ingest/batch",
        json=events,
        headers={"X-Vex-Key": "ag_test_key"},
    )
    assert response.status_code == 422


def test_health_check_redis_unreachable(mock_redis):
    """Health check returns 503 when Redis ping fails."""
    from app.auth import verify_api_key
    from app.main import create_app
    from fastapi.testclient import TestClient
    from shared.auth import KeyInfo

    mock_redis.ping = AsyncMock(side_effect=ConnectionError("Redis down"))
    app = create_app()
    app.state.redis = mock_redis
    app.dependency_overrides[verify_api_key] = lambda: KeyInfo(
        org_id="test-org", key_id="test-key", scopes=["ingest"]
    )
    c = TestClient(app)
    response = c.get("/health")
    assert response.status_code == 503
    assert "Redis unreachable" in response.json()["detail"]


def test_ingest_auth_error_with_retry_after(mock_redis):
    """AuthError with retry_after_seconds returns 429 with Retry-After header."""
    from app.main import create_app
    from fastapi.testclient import TestClient
    from unittest.mock import patch
    from shared.auth import AuthError

    app = create_app()
    app.state.redis = mock_redis

    with patch("app.auth.get_validator") as mock_get_validator:
        mock_validator = mock_get_validator.return_value
        mock_validator.validate.side_effect = AuthError(
            status_code=429, detail="Rate limit exceeded", retry_after_seconds=60
        )
        c = TestClient(app)
        response = c.post(
            "/v1/ingest",
            json={"agent_id": "x", "input": {}, "output": {}},
            headers={"X-Vex-Key": "some-key"},
        )
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"


def test_ingest_accepts_legacy_agentguard_key_header(mock_redis):
    """X-AgentGuard-Key header should be accepted as a fallback."""
    from app.main import create_app
    from fastapi.testclient import TestClient
    from unittest.mock import patch
    from shared.auth import KeyInfo

    app = create_app()
    app.state.redis = mock_redis

    with patch("app.auth.get_validator") as mock_get_validator:
        mock_validator = mock_get_validator.return_value
        mock_validator.validate.return_value = KeyInfo(
            org_id="test-org", key_id="test-key", scopes=["ingest"]
        )
        c = TestClient(app)
        response = c.post(
            "/v1/ingest",
            json={"agent_id": "x", "input": {}, "output": {}},
            headers={"X-AgentGuard-Key": "ag_legacy_key"},
        )
    assert response.status_code == 202
    mock_validator.validate.assert_called_once_with("ag_legacy_key")


def test_ingest_single_injects_org_id(client, mock_redis):
    """Authenticated org_id should be injected into event metadata."""
    response = client.post(
        "/v1/ingest",
        json={"agent_id": "bot", "input": {}, "output": {}},
        headers={"X-Vex-Key": "ag_test_key"},
    )
    assert response.status_code == 202
    # Verify the data sent to Redis includes org_id
    call_args = mock_redis.xadd.call_args
    import json as _json
    payload = _json.loads(call_args[0][1]["data"])
    assert payload["metadata"]["org_id"] == "test-org"


def test_batch_empty_events_list(client):
    """Batch with empty events list should return 422 (min_length not met) or 202 with 0 accepted."""
    response = client.post(
        "/v1/ingest/batch",
        json={"events": []},
        headers={"X-Vex-Key": "ag_test_key"},
    )
    # Empty list is valid per Pydantic (max_length=50, no min_length set)
    if response.status_code == 202:
        assert response.json()["accepted"] == 0
    else:
        assert response.status_code == 422
