import asyncio

import httpx
import pytest
import respx

from agentguard.models import ExecutionEvent
from agentguard.transport import AsyncTransport, SyncTransport


# ---------------------------------------------------------------------------
# AsyncTransport fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def transport():
    return AsyncTransport(
        api_url="https://api.agentguard.dev",
        api_key="ag_test_key",
        flush_interval_s=0.1,
        flush_batch_size=5,
        timeout_s=2.0,
    )


# ---------------------------------------------------------------------------
# AsyncTransport tests
# ---------------------------------------------------------------------------


def test_transport_creation(transport):
    assert transport.api_url == "https://api.agentguard.dev"
    assert transport._buffer == []


def test_transport_enqueue(transport):
    event = ExecutionEvent(agent_id="test", input={}, output={})
    transport.enqueue(event)
    assert len(transport._buffer) == 1


@respx.mock
@pytest.mark.asyncio
async def test_transport_flush_sends_batch(transport):
    route = respx.post("https://api.agentguard.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 3})
    )
    for _ in range(3):
        transport.enqueue(ExecutionEvent(agent_id="test", input={}, output={}))

    await transport.flush()

    assert route.called
    assert len(transport._buffer) == 0
    # Verify payload wraps events in {"events": [...]} to match API contract
    import json as _json
    request_body = _json.loads(route.calls.last.request.content)
    assert "events" in request_body
    assert isinstance(request_body["events"], list)
    assert len(request_body["events"]) == 3


@respx.mock
@pytest.mark.asyncio
async def test_transport_flush_empty_buffer_noop(transport):
    route = respx.post("https://api.agentguard.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202)
    )
    await transport.flush()
    assert not route.called


@respx.mock
@pytest.mark.asyncio
async def test_transport_auto_flush_on_batch_size():
    transport = AsyncTransport(
        api_url="https://api.agentguard.dev",
        api_key="ag_test_key",
        flush_interval_s=10.0,
        flush_batch_size=3,
        timeout_s=2.0,
    )
    route = respx.post("https://api.agentguard.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 3})
    )

    for _ in range(3):
        transport.enqueue(ExecutionEvent(agent_id="test", input={}, output={}))

    await asyncio.sleep(0.1)
    await transport.flush()
    assert route.call_count >= 1


@respx.mock
@pytest.mark.asyncio
async def test_transport_flush_failure_puts_events_back(transport):
    """On HTTP error the events should be returned to the buffer for retry."""
    respx.post("https://api.agentguard.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )
    for _ in range(3):
        transport.enqueue(ExecutionEvent(agent_id="test", input={}, output={}))

    await transport.flush()

    # Events should be back in the buffer for retry
    assert len(transport._buffer) == 3


@respx.mock
@pytest.mark.asyncio
async def test_transport_sends_api_key_header(transport):
    route = respx.post("https://api.agentguard.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 1})
    )
    transport.enqueue(ExecutionEvent(agent_id="test", input={}, output={}))
    await transport.flush()

    assert route.called
    request = route.calls.last.request
    assert request.headers["X-AgentGuard-Key"] == "ag_test_key"


@respx.mock
@pytest.mark.asyncio
async def test_transport_close_flushes_remaining(transport):
    route = respx.post("https://api.agentguard.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 2})
    )
    transport.enqueue(ExecutionEvent(agent_id="test", input={}, output={}))
    transport.enqueue(ExecutionEvent(agent_id="test", input={}, output={}))

    await transport.close()

    assert route.called
    assert len(transport._buffer) == 0


# ---------------------------------------------------------------------------
# SyncTransport tests
# ---------------------------------------------------------------------------


@respx.mock
def test_sync_transport_verify():
    route = respx.post("https://api.agentguard.dev/v1/verify").mock(
        return_value=httpx.Response(
            200,
            json={
                "execution_id": "exec-123",
                "confidence": 0.92,
                "action": "pass",
                "output": "verified",
                "corrections": None,
                "checks": {},
            },
        )
    )
    transport = SyncTransport(
        api_url="https://api.agentguard.dev",
        api_key="ag_test_key",
        timeout_s=2.0,
    )
    event = ExecutionEvent(agent_id="test", input={}, output={})
    result = transport.verify(event)
    assert result["confidence"] == 0.92
    assert result["action"] == "pass"
    assert route.called
    transport.close()


@respx.mock
def test_sync_transport_verify_raises_on_error():
    respx.post("https://api.agentguard.dev/v1/verify").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )
    transport = SyncTransport(
        api_url="https://api.agentguard.dev",
        api_key="ag_test_key",
        timeout_s=2.0,
    )
    event = ExecutionEvent(agent_id="test", input={}, output={})
    with pytest.raises(httpx.HTTPStatusError):
        transport.verify(event)
    transport.close()


@respx.mock
def test_sync_transport_sends_api_key_header():
    route = respx.post("https://api.agentguard.dev/v1/verify").mock(
        return_value=httpx.Response(
            200,
            json={
                "execution_id": "exec-123",
                "confidence": 0.95,
                "action": "pass",
                "output": "ok",
                "corrections": None,
                "checks": {},
            },
        )
    )
    transport = SyncTransport(
        api_url="https://api.agentguard.dev",
        api_key="ag_test_key",
        timeout_s=2.0,
    )
    event = ExecutionEvent(agent_id="test", input={}, output={})
    transport.verify(event)

    request = route.calls.last.request
    assert request.headers["X-AgentGuard-Key"] == "ag_test_key"
    transport.close()
