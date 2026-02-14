# Production Hardening Design

**Date:** 2026-02-15
**Goal:** Harden SDK and backend services for real user traffic (expected in 1-2 weeks)
**Scope:** 15 items across SDK (8) and backend (7). No new features.

## Context

An enterprise readiness review identified 16 issues (1 already fixed: org_id in alert service). These range from OOM-causing bugs to missing retries to compliance gaps. All fixes are incremental — no architectural changes.

## SDK Hardening (8 items)

### 1. Capped Event Buffer

**File:** `sdk/python/agentguard/transport.py`

- Add `max_buffer_size: int = 10_000` to `GuardConfig`
- When buffer is full, drop oldest events and log warning with count
- On retry failure, only re-add events if buffer has space

### 2. HTTP Retry with Exponential Backoff

**File:** `sdk/python/agentguard/transport.py`

- 3 retries with backoff: 0.1s, 0.2s, 0.4s
- Only retry on 5xx and network errors (not 4xx)
- After all retries fail, return events to buffer (respecting max size)

### 3. Event Loop Moved to Background Thread

**File:** `sdk/python/agentguard/guard.py`

- Move `asyncio.new_event_loop()` from `__init__` into `_flush_loop()` background thread
- Loop created and owned by flush thread only
- Remove `self._loop` from constructor
- Fixes compatibility with FastAPI and other async frameworks

### 4. API Key Validation on Init

**File:** `sdk/python/agentguard/guard.py`

- Reject empty/whitespace keys with `ConfigurationError`
- Reject keys shorter than 10 chars
- Strip whitespace from key

### 5. Granular HTTP Timeouts

**Files:** `sdk/python/agentguard/transport.py`, `sdk/python/agentguard/config.py`

- Replace scalar `timeout_s=30.0` with `httpx.Timeout(connect=5.0, read=timeout_s, write=10.0, pool=5.0)`
- Lower default `timeout_s` from 30 to 10 in `GuardConfig`

### 6. Connection Pool Limits

**File:** `sdk/python/agentguard/transport.py`

- Add `httpx.Limits(max_keepalive_connections=10, max_connections=20)` to both sync and async clients

### 7. PII Redaction in Logs

**Files:** `sdk/python/agentguard/guard.py`, `sdk/python/agentguard/config.py`

- Add `log_event_ids: bool = False` to `GuardConfig`
- Default: log only confidence/action, not execution_id or payloads
- When `True`: include execution_id for debugging

### 8. Session Thread-Safety Documentation

**File:** `sdk/python/agentguard/guard.py`

- Add docstring to `Session` class: NOT thread-safe, create one per thread
- No code changes, documentation only

## Backend Hardening (7 items)

### 9. DB Connection Pooling

**Files:** `services/storage-worker/app/db.py`, `services/alert-service/app/db.py`

- Add `pool_size=5, max_overflow=10, pool_pre_ping=True, pool_recycle=3600`
- Matches existing pattern in `shared/auth.py`

### 10. Remove Gateway Sleep Race Condition

**File:** `services/sync-gateway/app/routes.py`

- Remove `await asyncio.sleep(1)` between raw and verified event publishing
- Storage worker already handles missing rows gracefully (rowcount check + rollback)

### 11. DB Session Rollback on Errors

**Files:** `services/storage-worker/app/main.py`, `services/alert-service/app/main.py`

- Add `db_session.rollback()` in except blocks before `db_session.close()`
- Pattern: try → process → except → rollback, raise → finally → close

### 12. Redis Client Resilience

**Files:** All services using `redis.from_url()` (gateway, ingestion, async-worker, storage-worker, alert-service)

- Add: `socket_timeout=5.0`, `socket_connect_timeout=5.0`, `socket_keepalive=True`, `retry_on_timeout=True`, `health_check_interval=30`

### 13. Deep Health Checks

**Files:** `services/sync-gateway/app/routes.py`, `services/ingestion-api/app/routes.py`

- Gateway `/health`: ping Redis, return 503 if down
- Ingestion `/health`: ping Redis, return 503 if down
- Workers have no HTTP endpoints — skip

### 14. Structured Logging Fields

**Files:** All service error/warning log calls

- Add `extra={"execution_id": ..., "agent_id": ..., "org_id": ...}` to log calls
- No new logging framework — just structured fields on existing loggers

### 15. S3 Client Retries

**Files:** `services/storage-worker/app/s3_client.py`, `services/storage-worker/app/worker.py`

- Add `botocore.config.Config(retries={"max_attempts": 3, "mode": "adaptive"}, connect_timeout=5, read_timeout=10)`
- Wrap `put_object` in try/except — log error, don't crash worker

## Testing Strategy

- All SDK changes: unit tests (extend existing test suite)
- Backend changes: unit tests per service
- Live test after deployment: send events through full pipeline, verify no regressions
- Existing 176+ tests must continue passing

## Out of Scope

- New features (loop detection, human feedback, etc.)
- Logging framework changes (python-json-logger, structlog)
- Kubernetes health check probes (infra config)
- PyPI version bump (separate step after hardening)
