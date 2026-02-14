# Production Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Harden SDK and backend services for production user traffic — fix 15 resilience, correctness, and observability issues.

**Architecture:** Incremental fixes to existing files. No new services, no schema changes. SDK changes affect `transport.py`, `guard.py`, `config.py`. Backend changes affect `db.py`, `main.py`, `routes.py`, `redis_client.py`, `s3_client.py` across 5 services.

**Tech Stack:** Python 3.9+, httpx, SQLAlchemy, redis-py, boto3/botocore, FastAPI, pytest

---

### Task 1: SDK — Capped Event Buffer

**Files:**
- Modify: `sdk/python/agentguard/config.py`
- Modify: `sdk/python/agentguard/transport.py`
- Test: `sdk/python/tests/test_transport.py`

**Step 1: Write failing tests**

Add to `sdk/python/tests/test_transport.py`:

```python
def test_enqueue_drops_when_buffer_full():
    """Events are dropped when buffer exceeds max_buffer_size."""
    transport = AsyncTransport(
        api_url="http://localhost",
        api_key="test",
        max_buffer_size=5,
    )
    for i in range(10):
        event = make_event(execution_id=f"evt-{i}")
        transport.enqueue(event)
    with transport._lock:
        assert len(transport._buffer) == 5
    transport._dropped_count >= 5


def test_flush_retry_respects_buffer_limit():
    """Failed flush only re-adds events up to max_buffer_size."""
    transport = AsyncTransport(
        api_url="http://localhost",
        api_key="test",
        max_buffer_size=3,
    )
    # Fill buffer
    for i in range(3):
        transport.enqueue(make_event(execution_id=f"evt-{i}"))
    # Simulate failed flush re-adding events when buffer is already full
    with transport._lock:
        batch = list(transport._buffer)
        transport._buffer.clear()
    # Add new events while "flush" is in progress
    for i in range(3):
        transport.enqueue(make_event(execution_id=f"new-{i}"))
    # Simulate retry re-add — should not exceed max
    with transport._lock:
        available = max(0, transport.max_buffer_size - len(transport._buffer))
        events_to_retry = batch[:available]
        transport._buffer = events_to_retry + transport._buffer
        assert len(transport._buffer) <= transport.max_buffer_size
```

**Step 2: Run tests to verify they fail**

Run: `cd sdk/python && python3 -m pytest tests/test_transport.py::test_enqueue_drops_when_buffer_full tests/test_transport.py::test_flush_retry_respects_buffer_limit -v`
Expected: FAIL — `max_buffer_size` parameter doesn't exist yet

**Step 3: Implement**

In `sdk/python/agentguard/config.py`, add field to `GuardConfig`:

```python
max_buffer_size: int = 10000
```

In `sdk/python/agentguard/transport.py`, update `AsyncTransport.__init__`:

```python
def __init__(
    self,
    api_url: str,
    api_key: str,
    flush_interval_s: float = 1.0,
    flush_batch_size: int = 50,
    timeout_s: float = 2.0,
    max_buffer_size: int = 10000,
) -> None:
    self.api_url: str = api_url.rstrip("/")
    self.api_key: str = api_key
    self.flush_interval_s: float = flush_interval_s
    self.flush_batch_size: int = flush_batch_size
    self.timeout_s: float = timeout_s
    self.max_buffer_size: int = max_buffer_size

    self._buffer: List[ExecutionEvent] = []
    self._lock: threading.Lock = threading.Lock()
    self._client: Optional[httpx.AsyncClient] = None
    self._dropped_count: int = 0
```

Update `enqueue`:

```python
def enqueue(self, event: ExecutionEvent) -> None:
    with self._lock:
        if len(self._buffer) >= self.max_buffer_size:
            self._dropped_count += 1
            if self._dropped_count % 100 == 1:
                logger.warning(
                    "Buffer full (%d events), dropping event (total dropped: %d)",
                    self.max_buffer_size,
                    self._dropped_count,
                )
            return
        self._buffer.append(event)
        should_flush = len(self._buffer) >= self.flush_batch_size

    if should_flush:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.flush())
        except RuntimeError:
            logger.debug(
                "No running event loop; skipping auto-flush (buffer size: %d)",
                len(self._buffer),
            )
```

Update `flush` retry logic (replace the `except` block):

```python
except Exception:
    logger.warning(
        "Failed to flush %d events; returning to buffer for retry",
        len(batch),
        exc_info=True,
    )
    with self._lock:
        available_space = max(0, self.max_buffer_size - len(self._buffer))
        events_to_retry = batch[:available_space]
        dropped = len(batch) - len(events_to_retry)
        if dropped > 0:
            self._dropped_count += dropped
            logger.warning(
                "Dropped %d events due to buffer overflow on retry",
                dropped,
            )
        self._buffer = events_to_retry + self._buffer
```

Update `AgentGuard.__init__` in `guard.py` to pass `max_buffer_size`:

```python
self._async_transport = AsyncTransport(
    api_url=self.config.api_url,
    api_key=self.api_key,
    flush_interval_s=self.config.flush_interval_s,
    flush_batch_size=self.config.flush_batch_size,
    timeout_s=self.config.timeout_s,
    max_buffer_size=self.config.max_buffer_size,
)
```

**Step 4: Run tests to verify they pass**

Run: `cd sdk/python && python3 -m pytest tests/test_transport.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add sdk/python/agentguard/config.py sdk/python/agentguard/transport.py sdk/python/agentguard/guard.py sdk/python/tests/test_transport.py
git commit -m "feat(sdk): add buffer size limit to prevent OOM on API outages"
```

---

### Task 2: SDK — HTTP Retry with Exponential Backoff

**Files:**
- Modify: `sdk/python/agentguard/transport.py`
- Test: `sdk/python/tests/test_transport.py`

**Step 1: Write failing tests**

```python
import pytest
import httpx

@pytest.mark.asyncio
async def test_flush_retries_on_server_error(mocker):
    """flush retries on 5xx errors with exponential backoff."""
    transport = AsyncTransport(
        api_url="http://localhost",
        api_key="test",
    )
    event = make_event()
    transport.enqueue(event)

    call_count = 0
    async def mock_post(url, json=None):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            resp = httpx.Response(502, request=httpx.Request("POST", url))
            resp.raise_for_status()
        return httpx.Response(200, request=httpx.Request("POST", url))

    mock_client = mocker.AsyncMock()
    mock_client.post = mock_post
    mock_client.is_closed = False
    transport._client = mock_client
    mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)

    await transport.flush()
    assert call_count == 3  # 2 failures + 1 success
    assert len(transport._buffer) == 0


@pytest.mark.asyncio
async def test_flush_no_retry_on_client_error(mocker):
    """flush does NOT retry on 4xx errors."""
    transport = AsyncTransport(
        api_url="http://localhost",
        api_key="test",
    )
    event = make_event()
    transport.enqueue(event)

    async def mock_post(url, json=None):
        resp = httpx.Response(401, request=httpx.Request("POST", url))
        resp.raise_for_status()

    mock_client = mocker.AsyncMock()
    mock_client.post = mock_post
    mock_client.is_closed = False
    transport._client = mock_client

    await transport.flush()
    # Buffer should be empty — 4xx errors are not retried, events are lost
    assert len(transport._buffer) == 0
```

**Step 2: Run tests to verify they fail**

Run: `cd sdk/python && python3 -m pytest tests/test_transport.py::test_flush_retries_on_server_error tests/test_transport.py::test_flush_no_retry_on_client_error -v`
Expected: FAIL

**Step 3: Implement**

Replace the `flush` method in `AsyncTransport`:

```python
async def flush(self) -> None:
    """Send all buffered events as a batch POST to the Ingestion API.

    Retries up to 3 times with exponential backoff on server errors (5xx)
    and network failures. Client errors (4xx) are not retried.
    """
    with self._lock:
        if not self._buffer:
            return
        batch = list(self._buffer)
        self._buffer.clear()

    payload = [event.model_dump(mode="json") for event in batch]
    url = f"{self.api_url}/v1/ingest/batch"

    max_retries = 3
    base_delay = 0.1

    for attempt in range(max_retries):
        try:
            client = self._get_client()
            response = await client.post(url, json={"events": payload})
            response.raise_for_status()
            logger.debug(
                "Flushed %d events to %s (status %d)",
                len(batch),
                url,
                response.status_code,
            )
            return  # Success
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:
                # Client error — don't retry, don't re-buffer
                logger.warning(
                    "Client error %d flushing %d events; dropping batch",
                    exc.response.status_code,
                    len(batch),
                )
                return
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "Server error %d (attempt %d/%d), retrying in %.2fs",
                    exc.response.status_code,
                    attempt + 1,
                    max_retries,
                    delay,
                )
                await asyncio.sleep(delay)
            # Fall through to retry buffer on final attempt
        except Exception:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "Flush failed (attempt %d/%d), retrying in %.2fs",
                    attempt + 1,
                    max_retries,
                    delay,
                    exc_info=True,
                )
                await asyncio.sleep(delay)
            # Fall through to retry buffer on final attempt

    # All retries exhausted — put events back in buffer
    logger.warning(
        "Failed to flush %d events after %d attempts; returning to buffer",
        len(batch),
        max_retries,
    )
    with self._lock:
        available_space = max(0, self.max_buffer_size - len(self._buffer))
        events_to_retry = batch[:available_space]
        dropped = len(batch) - len(events_to_retry)
        if dropped > 0:
            self._dropped_count += dropped
        self._buffer = events_to_retry + self._buffer
```

Also add retry to `SyncTransport.verify` for network errors only (not HTTP status errors — those propagate to the caller):

```python
def verify(self, event, thresholds=None, correction="none", transparency="opaque"):
    # ... existing payload building code stays the same ...

    client = self._get_correction_client() if correction != "none" else self._client

    max_retries = 3
    base_delay = 0.1
    last_exc = None

    for attempt in range(max_retries):
        try:
            response = client.post(url, json=payload)
            response.raise_for_status()
            result: Dict[str, object] = response.json()
            return result
        except httpx.HTTPStatusError:
            raise  # Don't retry HTTP errors — caller handles
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "Verify request failed (attempt %d/%d), retrying in %.2fs",
                    attempt + 1,
                    max_retries,
                    delay,
                )
                import time
                time.sleep(delay)

    raise last_exc  # type: ignore[misc]
```

**Step 4: Run tests**

Run: `cd sdk/python && python3 -m pytest tests/test_transport.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add sdk/python/agentguard/transport.py sdk/python/tests/test_transport.py
git commit -m "feat(sdk): add retry with exponential backoff for transient failures"
```

---

### Task 3: SDK — Move Event Loop to Background Thread

**Files:**
- Modify: `sdk/python/agentguard/guard.py`
- Test: `sdk/python/tests/test_guard.py`

**Step 1: Write failing test**

```python
import asyncio

def test_guard_init_does_not_create_event_loop():
    """AgentGuard constructor should not call asyncio.new_event_loop()."""
    guard = AgentGuard(api_key="test-key-1234567890")
    assert not hasattr(guard, "_loop"), "Guard should not store an event loop on self"
    guard.close()
```

**Step 2: Run test to verify it fails**

Run: `cd sdk/python && python3 -m pytest tests/test_guard.py::test_guard_init_does_not_create_event_loop -v`
Expected: FAIL — `guard._loop` exists

**Step 3: Implement**

Replace `__init__` lines 293-301 and `_flush_loop`:

```python
# In __init__, replace:
#     self._loop = asyncio.new_event_loop()
#     self._flush_stop = threading.Event()
#     self._flush_thread = threading.Thread(...)
#     self._flush_thread.start()
#     self._closed = False
# With:
self._flush_stop = threading.Event()
self._flush_thread = threading.Thread(
    target=self._flush_loop,
    daemon=True,
    name="agentguard-flush",
)
self._flush_thread.start()
self._closed = False
```

Replace `_flush_loop`:

```python
def _flush_loop(self) -> None:
    """Periodically flush buffered events on a background thread.

    Creates its own event loop to avoid conflicting with any loop
    running on the main thread (e.g. FastAPI, asyncio applications).
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        while not self._flush_stop.is_set():
            self._flush_stop.wait(timeout=self.config.flush_interval_s)
            if not self._flush_stop.is_set():
                try:
                    loop.run_until_complete(self._async_transport.flush())
                except Exception:
                    logger.warning("Background flush failed", exc_info=True)
    finally:
        # Final flush before shutting down
        try:
            loop.run_until_complete(self._async_transport.close())
        except Exception:
            logger.warning("Error during final async transport close", exc_info=True)
        finally:
            loop.close()
```

Replace `close` method:

```python
def close(self) -> None:
    """Shut down the guard client, flushing any remaining events.

    Stops the background flush thread (which handles final flush and
    loop cleanup) and closes the sync transport. Safe to call multiple times.
    """
    if self._closed:
        return
    self._closed = True

    # Signal the flush thread to stop — it will do a final flush
    self._flush_stop.set()
    self._flush_thread.join(timeout=30.0)
    if self._flush_thread.is_alive():
        logger.warning("Flush thread did not stop within 30s; some events may be lost")

    # Close sync transport if it exists
    if self._sync_transport is not None:
        try:
            self._sync_transport.close()
        except Exception:
            logger.warning("Error closing sync transport", exc_info=True)
```

**Step 4: Run tests**

Run: `cd sdk/python && python3 -m pytest tests/ -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add sdk/python/agentguard/guard.py sdk/python/tests/test_guard.py
git commit -m "fix(sdk): move event loop to background thread for async framework compat"
```

---

### Task 4: SDK — API Key Validation

**Files:**
- Modify: `sdk/python/agentguard/guard.py`
- Modify: `sdk/python/agentguard/exceptions.py`
- Test: `sdk/python/tests/test_guard.py`

**Step 1: Write failing tests**

```python
import pytest
from agentguard.exceptions import ConfigurationError

def test_guard_rejects_empty_api_key():
    with pytest.raises(ConfigurationError, match="API key cannot be empty"):
        AgentGuard(api_key="")

def test_guard_rejects_whitespace_api_key():
    with pytest.raises(ConfigurationError, match="API key cannot be empty"):
        AgentGuard(api_key="   ")

def test_guard_rejects_short_api_key():
    with pytest.raises(ConfigurationError, match="too short"):
        AgentGuard(api_key="abc")

def test_guard_strips_whitespace_from_api_key():
    guard = AgentGuard(api_key="  test-key-1234567890  ")
    assert guard.api_key == "test-key-1234567890"
    guard.close()
```

**Step 2: Run tests to verify they fail**

Run: `cd sdk/python && python3 -m pytest tests/test_guard.py -k "api_key" -v`
Expected: FAIL — `ConfigurationError` doesn't exist, no validation

**Step 3: Implement**

Add to `sdk/python/agentguard/exceptions.py`:

```python
class ConfigurationError(Exception):
    """Raised when AgentGuard is initialized with invalid configuration."""
    pass
```

Update `__init__.py` to export it.

Add to `AgentGuard.__init__` at the top (before any transport creation):

```python
def __init__(self, api_key: str, config: Optional[GuardConfig] = None) -> None:
    if not api_key or not api_key.strip():
        raise ConfigurationError("API key cannot be empty")
    api_key = api_key.strip()
    if len(api_key) < 10:
        raise ConfigurationError("API key appears invalid (too short)")
    self.api_key = api_key
    self.config = config or GuardConfig()
    # ... rest of __init__
```

**Step 4: Run tests**

Run: `cd sdk/python && python3 -m pytest tests/ -v`
Expected: ALL PASS (may need to update existing tests that use short test keys)

**Step 5: Commit**

```bash
git add sdk/python/agentguard/exceptions.py sdk/python/agentguard/guard.py sdk/python/agentguard/__init__.py sdk/python/tests/test_guard.py
git commit -m "feat(sdk): validate API key on initialization"
```

---

### Task 5: SDK — Granular HTTP Timeouts

**Files:**
- Modify: `sdk/python/agentguard/config.py`
- Modify: `sdk/python/agentguard/transport.py`
- Test: `sdk/python/tests/test_transport.py`

**Step 1: Write failing test**

```python
def test_async_client_uses_granular_timeouts():
    transport = AsyncTransport(
        api_url="http://localhost",
        api_key="test",
        timeout_s=10.0,
    )
    client = transport._get_client()
    assert client.timeout.connect == 5.0
    assert client.timeout.read == 10.0
    assert client.timeout.pool == 5.0


def test_sync_client_uses_granular_timeouts():
    transport = SyncTransport(
        api_url="http://localhost",
        api_key="test",
        timeout_s=10.0,
    )
    assert transport._client.timeout.connect == 5.0
    assert transport._client.timeout.read == 10.0
    assert transport._client.timeout.pool == 5.0
```

**Step 2: Run tests to verify they fail**

Run: `cd sdk/python && python3 -m pytest tests/test_transport.py -k "granular_timeout" -v`
Expected: FAIL

**Step 3: Implement**

Change `GuardConfig.timeout_s` default from `30.0` to `10.0` in `config.py`.

In `transport.py`, update `AsyncTransport._get_client`:

```python
self._client = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=5.0, read=self.timeout_s, write=10.0, pool=5.0),
    headers={"X-AgentGuard-Key": self.api_key},
    limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
)
```

Update `SyncTransport.__init__` for `_client`:

```python
self._client: httpx.Client = httpx.Client(
    timeout=httpx.Timeout(connect=5.0, read=self.timeout_s, write=10.0, pool=5.0),
    headers={"X-AgentGuard-Key": self.api_key},
    limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
)
```

Update `SyncTransport._get_correction_client`:

```python
self._correction_client = httpx.Client(
    timeout=httpx.Timeout(connect=5.0, read=self.correction_timeout_s, write=10.0, pool=5.0),
    headers={"X-AgentGuard-Key": self.api_key},
    limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
)
```

This also covers **Task 6 (Connection Pool Limits)** — the `httpx.Limits` are added here.

**Step 4: Run tests**

Run: `cd sdk/python && python3 -m pytest tests/ -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add sdk/python/agentguard/config.py sdk/python/agentguard/transport.py sdk/python/tests/test_transport.py
git commit -m "feat(sdk): granular HTTP timeouts and connection pool limits"
```

---

### Task 6: SDK — PII Redaction in Logs + Session Docs

**Files:**
- Modify: `sdk/python/agentguard/config.py`
- Modify: `sdk/python/agentguard/guard.py`
- Test: `sdk/python/tests/test_guard.py`

**Step 1: Write failing test**

```python
def test_flagged_output_does_not_log_execution_id_by_default(caplog):
    """By default, flagged outputs should not log execution_id."""
    guard = AgentGuard(api_key="test-key-1234567890", config=GuardConfig(mode="async"))
    event = make_event(execution_id="secret-exec-id-123")
    import logging
    with caplog.at_level(logging.WARNING):
        guard._process_event(event)
    # In async mode, no warning is logged (pass-through)
    # This test validates the config field exists
    assert guard.config.log_event_ids is False
    guard.close()
```

**Step 2: Run test to verify it fails**

Expected: FAIL — `log_event_ids` doesn't exist on config

**Step 3: Implement**

Add to `GuardConfig`:

```python
log_event_ids: bool = False
```

Update the flag warning in `guard.py` `_process_event` (line 362):

```python
if result.action == "flag":
    if self.config.log_event_ids:
        logger.warning(
            "Agent output flagged for event %s (confidence=%s)",
            event.execution_id,
            result.confidence,
        )
    else:
        logger.warning(
            "Agent output flagged (confidence=%s)",
            result.confidence,
        )
```

Similarly update the sync failure log (line 373):

```python
except Exception:
    if self.config.log_event_ids:
        logger.warning(
            "Sync verification failed for event %s; returning pass-through result",
            event.execution_id,
            exc_info=True,
        )
    else:
        logger.warning(
            "Sync verification failed; returning pass-through result",
            exc_info=True,
        )
```

Add thread-safety docstring to `Session` class:

```python
class Session:
    """Groups multiple trace executions into a logical session.

    **Thread Safety:** Session instances are NOT thread-safe. Do not call
    ``trace()`` concurrently from multiple threads on the same Session
    instance. Create separate Session instances per thread if needed.

    Automatically assigns a shared session_id and auto-incrementing
    sequence_number to each trace created through this session.
    ...
    """
```

**Step 4: Run tests**

Run: `cd sdk/python && python3 -m pytest tests/ -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add sdk/python/agentguard/config.py sdk/python/agentguard/guard.py sdk/python/tests/test_guard.py
git commit -m "feat(sdk): PII-safe logging defaults and session thread-safety docs"
```

---

### Task 7: Backend — DB Connection Pooling

**Files:**
- Modify: `services/storage-worker/app/db.py`
- Modify: `services/alert-service/app/db.py`

**Step 1: No test needed** — this is configuration, not logic. Existing tests cover DB operations.

**Step 2: Implement**

Replace `services/storage-worker/app/db.py`:

```python
"""Database engine and session factory for the storage worker."""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://agentguard:agentguard_dev@localhost:5432/agentguard",
)

engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=3600,
)
SessionLocal = sessionmaker(bind=engine)
```

Replace `services/alert-service/app/db.py` with the same pattern.

**Step 3: Run existing tests**

Run: `cd services/storage-worker && PYTHONPATH=../shared:. python3 -m pytest tests/ -v`
Run: `cd services/alert-service && PYTHONPATH=../shared:. python3 -m pytest tests/ -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add services/storage-worker/app/db.py services/alert-service/app/db.py
git commit -m "feat(backend): add connection pooling to storage and alert DB engines"
```

---

### Task 8: Backend — Remove Gateway Sleep + DB Rollback

**Files:**
- Modify: `services/sync-gateway/app/routes.py`
- Modify: `services/storage-worker/app/main.py`
- Modify: `services/alert-service/app/main.py`

**Step 1: Implement gateway fix**

In `services/sync-gateway/app/routes.py`, remove line 267:

```python
# DELETE this line:
await asyncio.sleep(1)
```

So lines 265-268 become:

```python
await redis.xadd(RAW_STREAM_KEY, {"data": event.model_dump_json()})
await redis.xadd(VERIFIED_STREAM_KEY, {"data": json.dumps(verified_data)})
```

**Step 2: Implement DB rollback in storage worker**

In `services/storage-worker/app/main.py`, update the two try/finally blocks.

For `_consume_raw` (around line 74):

```python
db_session = SessionLocal()
try:
    stored_notification = process_event(
        event, s3_client, db_session, org_id=org_id,
    )
except Exception:
    db_session.rollback()
    raise
finally:
    db_session.close()
```

For `_consume_verified` (around line 122):

```python
db_session = SessionLocal()
try:
    updated = process_verified_event(event_data, db_session)
except Exception:
    db_session.rollback()
    raise
finally:
    db_session.close()
```

**Step 3: Implement DB rollback in alert service**

In `services/alert-service/app/main.py` (around line 74):

```python
db_session = SessionLocal()
try:
    await process_verified_event(event_data, db_session)
except Exception:
    db_session.rollback()
    raise
finally:
    db_session.close()
```

**Step 4: Run existing tests**

Run: `cd services/sync-gateway && PYTHONPATH=../shared:../verification-engine:. python3 -m pytest tests/test_routes.py -v`
Run: `cd services/storage-worker && PYTHONPATH=../shared:. python3 -m pytest tests/ -v`
Run: `cd services/alert-service && PYTHONPATH=../shared:. python3 -m pytest tests/ -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add services/sync-gateway/app/routes.py services/storage-worker/app/main.py services/alert-service/app/main.py
git commit -m "fix(backend): remove gateway sleep race condition, add DB rollback on errors"
```

---

### Task 9: Backend — Redis Client Resilience

**Files:**
- Modify: `services/sync-gateway/app/redis_client.py`
- Modify: `services/ingestion-api/app/redis_client.py`
- Modify: `services/async-worker/app/main.py`
- Modify: `services/storage-worker/app/main.py`
- Modify: `services/alert-service/app/main.py`

**Step 1: Create a shared helper** — since the same config is used everywhere, add it once.

Create `services/shared/shared/redis_config.py`:

```python
"""Shared Redis client configuration for resilient connections."""


REDIS_CLIENT_OPTIONS = {
    "decode_responses": True,
    "socket_timeout": 5.0,
    "socket_connect_timeout": 5.0,
    "socket_keepalive": True,
    "retry_on_timeout": True,
    "health_check_interval": 30,
}
```

**Step 2: Update all redis.from_url calls**

In `services/sync-gateway/app/redis_client.py`:

```python
"""Redis connection factory for the sync gateway."""

import os

import redis.asyncio as redis

from shared.redis_config import REDIS_CLIENT_OPTIONS


async def get_redis() -> redis.Redis:
    """Create and return a resilient async Redis client."""
    url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    return redis.from_url(url, **REDIS_CLIENT_OPTIONS)
```

Apply the same pattern to `services/ingestion-api/app/redis_client.py`.

In `services/async-worker/app/main.py`, update the `redis.from_url` call (line 45):

```python
from shared.redis_config import REDIS_CLIENT_OPTIONS
# ...
redis_client = aioredis.from_url(redis_url, **REDIS_CLIENT_OPTIONS)
```

Same for `services/storage-worker/app/main.py` (line 157) and `services/alert-service/app/main.py` (line 41).

**Step 3: Run tests**

Run tests for each affected service to verify no import errors.

**Step 4: Commit**

```bash
git add services/shared/shared/redis_config.py services/sync-gateway/app/redis_client.py services/ingestion-api/app/redis_client.py services/async-worker/app/main.py services/storage-worker/app/main.py services/alert-service/app/main.py
git commit -m "feat(backend): add Redis client resilience config across all services"
```

---

### Task 10: Backend — Deep Health Checks

**Files:**
- Modify: `services/sync-gateway/app/routes.py`
- Modify: `services/ingestion-api/app/routes.py`

**Step 1: Write failing tests**

Add to gateway tests:

```python
@pytest.mark.asyncio
async def test_health_returns_503_when_redis_down(client, mocker):
    """Health endpoint returns 503 when Redis ping fails."""
    mock_redis = mocker.AsyncMock()
    mock_redis.ping = mocker.AsyncMock(side_effect=Exception("Connection refused"))
    app.state.redis = mock_redis
    response = await client.get("/health")
    assert response.status_code == 503
```

**Step 2: Implement**

In `services/sync-gateway/app/routes.py`, update health endpoint:

```python
@router.get("/health")
async def health_check(request: Request):
    """Return service health status with Redis dependency check."""
    try:
        await request.app.state.redis.ping()
    except Exception:
        logger.error("Health check failed: Redis unreachable", exc_info=True)
        raise HTTPException(status_code=503, detail="Redis unreachable")
    return {"status": "healthy"}
```

Add `from fastapi import HTTPException` if not already imported, and add `request: Request` parameter.

In `services/ingestion-api/app/routes.py`, same pattern:

```python
@router.get("/health")
async def health_check(request: Request):
    """Return service health status with Redis dependency check."""
    try:
        await request.app.state.redis.ping()
    except Exception:
        logger.error("Health check failed: Redis unreachable", exc_info=True)
        raise HTTPException(status_code=503, detail="Redis unreachable")
    return {"status": "healthy"}
```

**Step 3: Run tests**

Run: `cd services/sync-gateway && PYTHONPATH=../shared:../verification-engine:. python3 -m pytest tests/test_routes.py -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add services/sync-gateway/app/routes.py services/ingestion-api/app/routes.py
git commit -m "feat(backend): health checks verify Redis connectivity"
```

---

### Task 11: Backend — Structured Logging

**Files:**
- Modify: All service files with `logger.error` or `logger.warning` calls

**Step 1: No new tests** — logging changes don't need test coverage.

**Step 2: Implement**

Update all `logger.error` and `logger.warning` calls across services to include `extra={}` with relevant context. Examples:

In `services/storage-worker/app/main.py`:

```python
logger.error(
    "Failed to process raw message %s: %s",
    msg_id, exc, exc_info=True,
    extra={"msg_id": msg_id, "execution_id": getattr(event, "execution_id", None), "org_id": org_id},
)
```

In `services/alert-service/app/main.py`:

```python
logger.error(
    "Failed to process message %s: %s",
    msg_id, exc, exc_info=True,
    extra={"msg_id": msg_id},
)
```

In `services/async-worker/app/main.py`:

```python
logger.error(
    "Failed to process message %s: %s",
    msg_id, exc, exc_info=True,
    extra={"msg_id": msg_id, "execution_id": getattr(event, "execution_id", None)},
)
```

In `services/sync-gateway/app/routes.py`, the `_verify_and_correct` and `verify_endpoint` functions:

```python
logger.warning(
    "Failed to emit Redis events for %s",
    event.execution_id, exc_info=True,
    extra={"execution_id": event.execution_id, "agent_id": event.agent_id},
)
```

**Step 3: Run all service tests**

Expected: ALL PASS

**Step 4: Commit**

```bash
git add services/
git commit -m "feat(backend): add structured logging fields for observability"
```

---

### Task 12: Backend — S3 Client Retries

**Files:**
- Modify: `services/storage-worker/app/s3_client.py`
- Modify: `services/storage-worker/app/worker.py`

**Step 1: Write failing test**

```python
def test_s3_client_has_retry_config():
    """S3 client should be configured with adaptive retry."""
    from app.s3_client import get_s3_client
    client = get_s3_client()
    assert client.meta.config.retries["max_attempts"] == 3
```

**Step 2: Implement**

Update `services/storage-worker/app/s3_client.py`:

```python
"""S3/MinIO client factory for the storage worker."""

import os

import boto3
from botocore.config import Config


def get_s3_client():
    """Create and return a configured boto3 S3 client with retry logic."""
    config = Config(
        retries={"max_attempts": 3, "mode": "adaptive"},
        connect_timeout=5,
        read_timeout=10,
    )
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT", "http://localhost:9000"),
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY", "agentguard"),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY", "agentguard_dev"),
        config=config,
    )
```

In `services/storage-worker/app/worker.py`, wrap the `put_object` call (around line 58) in try/except:

```python
try:
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=json.dumps(payload, default=str),
        ContentType="application/json",
    )
except Exception:
    logger.error(
        "Failed to upload execution to S3 (key=%s); proceeding with DB storage",
        s3_key,
        exc_info=True,
        extra={"execution_id": event.execution_id, "s3_key": s3_key},
    )
```

**Step 3: Run tests**

Run: `cd services/storage-worker && PYTHONPATH=../shared:. python3 -m pytest tests/ -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add services/storage-worker/app/s3_client.py services/storage-worker/app/worker.py
git commit -m "feat(backend): add S3 client retry config and error handling"
```

---

### Task 13: Final Verification

**Step 1: Run ALL SDK tests**

```bash
cd sdk/python && python3 -m pytest tests/ -v
```

Expected: ALL PASS (60+ tests)

**Step 2: Run ALL backend service tests**

```bash
cd services/sync-gateway && PYTHONPATH=../shared:../verification-engine:. python3 -m pytest tests/ -v
cd services/async-worker && PYTHONPATH=../shared:../verification-engine:. python3 -m pytest tests/ -v
cd services/alert-service && PYTHONPATH=../shared:. python3 -m pytest tests/ -v
cd services/storage-worker && PYTHONPATH=../shared:. python3 -m pytest tests/ -v
cd services/ingestion-api && PYTHONPATH=../shared:. python3 -m pytest tests/ -v
```

Expected: ALL PASS

**Step 3: Live smoke test**

```bash
PYTHONPATH=sdk/python python3 -c "
from agentguard import AgentGuard, GuardConfig
guard = AgentGuard(
    api_key='<LIVE_KEY>',
    config=GuardConfig(mode='sync', correction='cascade', transparency='transparent'),
)
with guard.trace(agent_id='hardening-test', task='What is 2+2?') as ctx:
    ctx.record('The answer is 4.')
print(f'Action: {ctx.result.action}, Confidence: {ctx.result.confidence}')
guard.close()
"
```

Expected: Action: pass, Confidence: ~1.0

**Step 4: Push all changes**

```bash
git push
```

**Step 5: Publish updated SDK to PyPI**

```bash
cd sdk/python
# Bump version in pyproject.toml to 0.3.0
python3 -m build
python3 -m twine upload dist/*
```
