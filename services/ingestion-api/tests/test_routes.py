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
        headers={"X-AgentGuard-Key": "ag_test_key"},
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
        headers={"X-AgentGuard-Key": "ag_test_key"},
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
    response = client_no_auth.post(
        "/v1/ingest", json={"agent_id": "x", "input": {}, "output": {}}
    )
    assert response.status_code == 401


def test_ingest_rejects_invalid_payload(client):
    response = client.post(
        "/v1/ingest",
        json={"bad": "data"},
        headers={"X-AgentGuard-Key": "ag_test_key"},
    )
    assert response.status_code == 422


def test_batch_rejects_over_50_events(client):
    events = {
        "events": [
            {"agent_id": f"bot-{i}", "input": {}, "output": {}} for i in range(51)
        ]
    }
    response = client.post(
        "/v1/ingest/batch",
        json=events,
        headers={"X-AgentGuard-Key": "ag_test_key"},
    )
    assert response.status_code == 422
