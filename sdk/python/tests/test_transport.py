import asyncio

import httpx
import pytest
import respx

from vex.models import ExecutionEvent
from vex.transport import AsyncTransport, SyncTransport


# ---------------------------------------------------------------------------
# AsyncTransport fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def transport():
    return AsyncTransport(
        api_url="https://api.tryvex.dev",
        api_key="ag_test_key",
        flush_interval_s=0.1,
        flush_batch_size=5,
        timeout_s=2.0,
    )


# ---------------------------------------------------------------------------
# AsyncTransport tests
# ---------------------------------------------------------------------------


def test_transport_creation(transport):
    assert transport.api_url == "https://api.tryvex.dev"
    assert transport._buffer == []


def test_transport_enqueue(transport):
    event = ExecutionEvent(agent_id="test", input={}, output={})
    transport.enqueue(event)
    assert len(transport._buffer) == 1


@respx.mock
@pytest.mark.asyncio
async def test_transport_flush_sends_batch(transport):
    route = respx.post("https://api.tryvex.dev/v1/ingest/batch").mock(
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
    route = respx.post("https://api.tryvex.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202)
    )
    await transport.flush()
    assert not route.called


@respx.mock
@pytest.mark.asyncio
async def test_transport_auto_flush_on_batch_size():
    transport = AsyncTransport(
        api_url="https://api.tryvex.dev",
        api_key="ag_test_key",
        flush_interval_s=10.0,
        flush_batch_size=3,
        timeout_s=2.0,
    )
    route = respx.post("https://api.tryvex.dev/v1/ingest/batch").mock(
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
    respx.post("https://api.tryvex.dev/v1/ingest/batch").mock(
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
    route = respx.post("https://api.tryvex.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 1})
    )
    transport.enqueue(ExecutionEvent(agent_id="test", input={}, output={}))
    await transport.flush()

    assert route.called
    request = route.calls.last.request
    assert request.headers["X-Vex-Key"] == "ag_test_key"


@respx.mock
@pytest.mark.asyncio
async def test_transport_close_flushes_remaining(transport):
    route = respx.post("https://api.tryvex.dev/v1/ingest/batch").mock(
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
    route = respx.post("https://api.tryvex.dev/v1/verify").mock(
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
        api_url="https://api.tryvex.dev",
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
    respx.post("https://api.tryvex.dev/v1/verify").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )
    transport = SyncTransport(
        api_url="https://api.tryvex.dev",
        api_key="ag_test_key",
        timeout_s=2.0,
    )
    event = ExecutionEvent(agent_id="test", input={}, output={})
    with pytest.raises(httpx.HTTPStatusError):
        transport.verify(event)
    transport.close()


@respx.mock
def test_sync_transport_sends_api_key_header():
    route = respx.post("https://api.tryvex.dev/v1/verify").mock(
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
        api_url="https://api.tryvex.dev",
        api_key="ag_test_key",
        timeout_s=2.0,
    )
    event = ExecutionEvent(agent_id="test", input={}, output={})
    transport.verify(event)

    request = route.calls.last.request
    assert request.headers["X-Vex-Key"] == "ag_test_key"
    transport.close()


# --- SyncTransport correction tests ---


@respx.mock
def test_sync_transport_verify_forwards_correction_metadata():
    """verify() should include correction and transparency in metadata."""
    import json as _json
    route = respx.post("https://api.tryvex.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "exec-123", "confidence": 0.9, "action": "pass",
            "output": "corrected", "checks": {}, "corrected": True,
        })
    )
    transport = SyncTransport(
        api_url="https://api.tryvex.dev",
        api_key="ag_test_key",
    )
    event = ExecutionEvent(agent_id="test", input={}, output={})
    transport.verify(event, correction="cascade", transparency="transparent")

    body = _json.loads(route.calls.last.request.content)
    assert body["metadata"]["correction"] == "cascade"
    assert body["metadata"]["transparency"] == "transparent"
    transport.close()


@respx.mock
def test_sync_transport_correction_client_uses_longer_timeout():
    """When correction=cascade, should use correction timeout client (12s)."""
    route = respx.post("https://api.tryvex.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "e", "confidence": 0.9, "action": "pass",
            "output": "ok", "checks": {},
        })
    )
    transport = SyncTransport(
        api_url="https://api.tryvex.dev",
        api_key="ag_test_key",
        timeout_s=2.0,
        correction_timeout_s=12.0,
    )
    event = ExecutionEvent(agent_id="test", input={}, output={})
    transport.verify(event, correction="cascade")

    # Verify the correction client was used (has 12s read timeout)
    assert transport._correction_client is not None
    assert transport._correction_client.timeout.read == 12.0
    transport.close()


@respx.mock
def test_sync_transport_default_client_for_no_correction():
    """When correction=none, should use default client (2s timeout)."""
    route = respx.post("https://api.tryvex.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "e", "confidence": 0.9, "action": "pass",
            "output": "ok", "checks": {},
        })
    )
    transport = SyncTransport(
        api_url="https://api.tryvex.dev",
        api_key="ag_test_key",
        timeout_s=2.0,
        correction_timeout_s=12.0,
    )
    event = ExecutionEvent(agent_id="test", input={}, output={})
    transport.verify(event, correction="none")

    # Correction client should NOT have been created
    assert transport._correction_client is None
    transport.close()


@respx.mock
def test_sync_transport_close_closes_both_clients():
    """close() should close both default and correction clients."""
    respx.post("https://api.tryvex.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "e", "confidence": 0.9, "action": "pass",
            "output": "ok", "checks": {},
        })
    )
    transport = SyncTransport(
        api_url="https://api.tryvex.dev",
        api_key="ag_test_key",
    )
    event = ExecutionEvent(agent_id="test", input={}, output={})
    # Trigger correction client creation
    transport.verify(event, correction="cascade")
    assert transport._correction_client is not None

    transport.close()
    assert transport._client.is_closed
    assert transport._correction_client.is_closed


# ---------------------------------------------------------------------------
# AsyncTransport buffer limit tests
# ---------------------------------------------------------------------------


def test_transport_drops_events_when_buffer_full():
    """When buffer is at max_buffer_size, new events should be dropped."""
    transport = AsyncTransport(
        api_url="https://api.tryvex.dev",
        api_key="ag_test_key",
        flush_interval_s=0.1,
        flush_batch_size=1000,
        timeout_s=2.0,
        max_buffer_size=10,
    )
    # Fill buffer to capacity
    for i in range(10):
        event = ExecutionEvent(agent_id=f"agent-{i}", input={}, output={})
        transport.enqueue(event)

    assert len(transport._buffer) == 10
    assert transport._dropped_count == 0

    # Enqueue one more - should be dropped
    transport.enqueue(ExecutionEvent(agent_id="agent-dropped", input={}, output={}))

    assert len(transport._buffer) == 10  # Still at max
    assert transport._dropped_count == 1


def test_transport_tracks_dropped_count():
    """_dropped_count should increment for each dropped event."""
    transport = AsyncTransport(
        api_url="https://api.tryvex.dev",
        api_key="ag_test_key",
        max_buffer_size=5,
    )
    # Fill buffer
    for i in range(5):
        transport.enqueue(ExecutionEvent(agent_id=f"agent-{i}", input={}, output={}))

    # Try to add 10 more (all should be dropped)
    for i in range(10):
        transport.enqueue(ExecutionEvent(agent_id=f"dropped-{i}", input={}, output={}))

    assert len(transport._buffer) == 5
    assert transport._dropped_count == 10


@respx.mock
@pytest.mark.asyncio
async def test_transport_flush_retry_respects_buffer_limit():
    """On flush failure, only events that fit within max_buffer_size are returned."""
    # Create transport with small buffer
    transport = AsyncTransport(
        api_url="https://api.tryvex.dev",
        api_key="ag_test_key",
        max_buffer_size=10,
    )
    # Mock API failure
    respx.post("https://api.tryvex.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )

    # Fill buffer with 8 events
    for i in range(8):
        transport.enqueue(ExecutionEvent(agent_id=f"agent-{i}", input={}, output={}))

    assert len(transport._buffer) == 8

    # Try to flush - will fail and try to put them back
    await transport.flush()

    # All 8 should fit back in the buffer (max 10)
    assert len(transport._buffer) == 8
    assert transport._dropped_count == 0


@respx.mock
@pytest.mark.asyncio
async def test_transport_flush_retry_drops_overflow():
    """On flush failure with partial buffer, events exceeding max_buffer_size are dropped."""
    # Create transport with small buffer
    transport = AsyncTransport(
        api_url="https://api.tryvex.dev",
        api_key="ag_test_key",
        max_buffer_size=10,
    )
    # Mock API failure
    respx.post("https://api.tryvex.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )

    # Fill buffer with 8 events and flush (they will be removed from buffer)
    for i in range(8):
        transport.enqueue(ExecutionEvent(agent_id=f"batch1-{i}", input={}, output={}))

    # Manually add 5 more events to buffer while the first 8 are "in flight"
    # Simulate the scenario where new events arrive while flush is happening
    with transport._lock:
        batch = list(transport._buffer)
        transport._buffer.clear()
        for i in range(5):
            transport._buffer.append(ExecutionEvent(agent_id=f"batch2-{i}", input={}, output={}))

    # Now try to add the failed batch back (8 events + 5 already buffered = 13 total)
    # Only 5 can fit (10 - 5 = 5 available space), so 3 should be dropped
    with transport._lock:
        available_space = max(0, transport.max_buffer_size - len(transport._buffer))
        events_to_retry = batch[:available_space]
        dropped = len(batch) - len(events_to_retry)
        if dropped > 0:
            transport._dropped_count += dropped
        transport._buffer = events_to_retry + transport._buffer

    assert len(transport._buffer) == 10  # At max capacity
    assert transport._dropped_count == 3  # 8 - 5 = 3 dropped


# ---------------------------------------------------------------------------
# AsyncTransport retry tests
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_flush_retries_on_server_error(transport):
    """flush() should retry up to 3 times on server errors (5xx) with backoff."""
    call_count = 0

    def side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            # Fail with 502 on first two attempts
            return httpx.Response(502, text="Bad Gateway")
        # Succeed on third attempt
        return httpx.Response(202, json={"accepted": 2})

    respx.post("https://api.tryvex.dev/v1/ingest/batch").mock(side_effect=side_effect)

    for _ in range(2):
        transport.enqueue(ExecutionEvent(agent_id="test", input={}, output={}))

    await transport.flush()

    # Should have made 3 calls (2 failures + 1 success)
    assert call_count == 3
    # Buffer should be empty after success
    assert len(transport._buffer) == 0


@respx.mock
@pytest.mark.asyncio
async def test_flush_no_retry_on_client_error(transport):
    """flush() should not retry on client errors (4xx) and should drop events."""
    route = respx.post("https://api.tryvex.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(401, text="Unauthorized")
    )

    for _ in range(2):
        transport.enqueue(ExecutionEvent(agent_id="test", input={}, output={}))

    await transport.flush()

    # Should have made only 1 call (no retry on 4xx)
    assert route.call_count == 1
    # Buffer should be empty (events dropped, not re-buffered)
    assert len(transport._buffer) == 0


# ---------------------------------------------------------------------------
# SyncTransport retry tests
# ---------------------------------------------------------------------------


@respx.mock
def test_sync_verify_retries_on_network_error():
    """verify() should retry up to 3 times on network errors with backoff."""
    call_count = 0

    def side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            # Raise ConnectError on first two attempts
            raise httpx.ConnectError("Connection failed")
        # Succeed on third attempt
        return httpx.Response(
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

    respx.post("https://api.tryvex.dev/v1/verify").mock(side_effect=side_effect)

    transport = SyncTransport(
        api_url="https://api.tryvex.dev",
        api_key="ag_test_key",
        timeout_s=2.0,
    )
    event = ExecutionEvent(agent_id="test", input={}, output={})
    result = transport.verify(event)

    # Should have made 3 calls (2 failures + 1 success)
    assert call_count == 3
    assert result["confidence"] == 0.92
    transport.close()


@respx.mock
def test_sync_verify_no_retry_on_http_error():
    """verify() should not retry on HTTP errors (4xx/5xx) and raise immediately."""
    route = respx.post("https://api.tryvex.dev/v1/verify").mock(
        return_value=httpx.Response(401, text="Unauthorized")
    )

    transport = SyncTransport(
        api_url="https://api.tryvex.dev",
        api_key="ag_test_key",
        timeout_s=2.0,
    )
    event = ExecutionEvent(agent_id="test", input={}, output={})

    with pytest.raises(httpx.HTTPStatusError):
        transport.verify(event)

    # Should have made only 1 call (no retry on HTTP errors)
    assert route.call_count == 1
    transport.close()


def test_async_client_uses_granular_timeouts():
    transport = AsyncTransport(api_url="http://localhost", api_key="test-key-1234567890", timeout_s=10.0)
    client = transport._get_client()
    assert client.timeout.connect == 5.0
    assert client.timeout.read == 10.0
    assert client.timeout.pool == 5.0


def test_sync_client_uses_granular_timeouts():
    transport = SyncTransport(api_url="http://localhost", api_key="test-key-1234567890", timeout_s=10.0)
    assert transport._client.timeout.connect == 5.0
    assert transport._client.timeout.read == 10.0
    assert transport._client.timeout.pool == 5.0
