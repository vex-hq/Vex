# Phase 2: Core Reliability — Design Document

**Date:** February 11, 2026
**Status:** Approved
**Goal:** Real-time verification with threshold-based actions.
**Timeline:** Weeks 4-6 (3 weeks)

---

## Overview

Phase 1 shipped observability: trace every execution, store it, display it. Phase 2 adds **active verification** — the system now judges every agent output for schema compliance, hallucination, and task drift, then takes action (pass/flag/block) based on confidence thresholds.

### Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| LLM provider abstraction | LiteLLM | Provider-agnostic, single interface, supports 100+ models. Configurable per deployment. |
| LLM strategy | Single configurable model (no tiered escalation) | Keep it simple. Tiered routing adds complexity without proven value yet. Add later if needed. |
| Billing/credits | Deferred | Build the verification engine first. Credit metering wraps the engine later as middleware — clean seam. |
| Alert delivery | Webhooks only | Simplest useful alert mechanism. Slack/PagerDuty/in-app come later as delivery adapters. |
| Engine architecture | Shared library, async-first | Used identically by Sync Gateway (inline) and Async Worker (background). Both paths produce identical results. |

---

## Build Order (8 Tasks)

```
1. DB migrations         — check_results + alerts tables
2. Verification Engine   — shared lib: schema, hallucination, drift, confidence, LLM client
3. Sync Gateway          — POST /v1/verify, runs engine in-process, 2s timeout
4. Async Worker          — Redis consumer, runs engine, emits verified events
5. Alert Service         — Redis consumer, webhook delivery + retry
6. SDK updates           — sync mode, threshold config, enriched GuardResult
7. Dashboard updates     — verification in traces, failures feed, confidence column
8. Integration tests     — end-to-end sync + async verification paths
```

Each task depends on the one above it.

---

## 1. Verification Engine (Shared Library)

**Package:** `services/verification-engine/`

```
services/verification-engine/
├── engine/
│   ├── __init__.py
│   ├── schema_validator.py    # JSON Schema validation, deterministic
│   ├── hallucination.py       # LLM claim extraction + grounding
│   ├── drift.py               # LLM task relevance scoring
│   ├── confidence.py          # Weighted composite scorer
│   ├── llm_client.py          # LiteLLM wrapper, single model
│   ├── pipeline.py            # Orchestrator: runs all checks, parallel where possible
│   └── models.py              # CheckResult, VerificationResult Pydantic models
├── tests/
├── pyproject.toml
```

### Pipeline (`pipeline.py`)

```python
async def verify(event, schema=None, ground_truth=None, config=None) -> VerificationResult:
    # 1. Schema validation (deterministic, <50ms)
    schema_result = schema_validator.validate(event.output, schema)

    # 2. Hallucination + drift in parallel (LLM, ~200-400ms)
    hallucination_result, drift_result = await asyncio.gather(
        hallucination.check(event.output, ground_truth),
        drift.check(event.output, event.task),
    )

    # 3. Confidence scoring
    confidence = confidence_scorer.compute(
        schema=schema_result,
        hallucination=hallucination_result,
        drift=drift_result,
        weights=config.weights if config else DEFAULT_WEIGHTS,
    )

    # 4. Action routing
    action = route_action(confidence, config.thresholds if config else DEFAULT_THRESHOLDS)

    return VerificationResult(
        confidence=confidence,
        action=action,
        checks={
            "schema": schema_result,
            "hallucination": hallucination_result,
            "drift": drift_result,
        },
    )
```

### LLM Client (`llm_client.py`)

- Uses LiteLLM for provider abstraction
- Single model configurable via env var: `VERIFICATION_MODEL` (default: `claude-haiku-4-5-20251001`)
- Timeout: 5s per call. On timeout, returns `score=None` (treated as "unable to verify")
- Future billing hook: credit check wraps `llm_client.call()` as middleware

### Confidence Scoring

```
confidence = (w1 * schema_score) + (w2 * hallucination_score) + (w3 * drift_score)
```

Default weights: `w1=0.3, w2=0.4, w3=0.3` (hallucination weighted highest — fabricated data is the highest-risk failure mode). Weights configurable per agent.

### Action Routing

| Confidence | Action |
|---|---|
| >= 0.8 | pass |
| >= 0.5 | flag |
| < 0.5 | block |

Thresholds configurable via `ThresholdConfig` (already exists in SDK).

---

## 2. Sync Verification Gateway

**Service:** `services/sync-gateway/`

```
services/sync-gateway/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI app, lifespan
│   └── routes.py        # POST /v1/verify, GET /health
├── tests/
├── pyproject.toml
├── Dockerfile
```

### `POST /v1/verify` Flow

1. Receive `VerifyRequest` (inherits from `IngestEvent`)
2. Call `engine.pipeline.verify(event)` — runs schema + hallucination + drift
3. Apply threshold config → determine action (pass/flag/block)
4. Emit verified event to Redis stream `executions.verified` (for storage + alerts)
5. Return `VerifyResponse` with confidence, action, per-check results

### 2-Second Hard Timeout

If the engine hasn't completed in 2 seconds:
- Return original output with `action: "pass"`, `confidence: null`
- Still emit to Redis for async re-verification in the background
- The agent is never blocked for more than 2s

### Key Design Choice

The gateway does NOT write to the database. It only emits to Redis. The storage worker handles all DB persistence. This keeps both sync and async paths consistent — one writer to the DB.

---

## 3. Async Verification Worker

**Service:** `services/async-worker/`

```
services/async-worker/
├── app/
│   ├── __init__.py
│   ├── main.py          # Redis consumer loop
│   └── worker.py        # Process event: run engine, emit results
├── tests/
├── pyproject.toml
├── Dockerfile
```

### Flow

1. Consumes from `executions.raw` stream (separate consumer group from storage worker)
2. Runs `engine.pipeline.verify(event)` on each event
3. Writes results to `executions.verified` stream
4. Storage worker picks up verified events and writes `check_results` rows

### Data Flow (Phase 2)

```
SDK (async) → Ingestion API → executions.raw
                                    │
                    ┌───────────────┼───────────────┐
                    ▼                               ▼
            Storage Worker                  Async Verification Worker
          (writes execution row)              (runs engine checks)
                                                    │
                                                    ▼
                                            executions.verified
                                                    │
                                    ┌───────────────┼───────────────┐
                                    ▼                               ▼
                            Storage Worker                    Alert Service
                        (writes check_results,            (fires webhooks for
                         updates confidence/action)        flag/block events)
```

Two consumer groups on `executions.raw` — storage worker and async verification worker operate independently. No ordering dependency.

No timeout pressure — unlike the sync gateway, the async worker can take as long as needed for LLM calls.

---

## 4. Alert Service

**Service:** `services/alert-service/`

```
services/alert-service/
├── app/
│   ├── __init__.py
│   ├── main.py          # Redis consumer loop
│   ├── worker.py        # Process alert: lookup config, fire webhook
│   └── webhook.py       # HTTP delivery with retry logic
├── tests/
├── pyproject.toml
├── Dockerfile
```

### Flow

1. Consumes from `executions.verified` stream
2. Filters: only processes `flag` and `block` events (skips `pass`)
3. Looks up webhook URL from agent config (env var or config file for MVP)
4. Fires `POST` to webhook URL with alert payload
5. Retries 3x with exponential backoff (1s, 2s, 4s) on failure
6. Writes delivery status to `alerts` table

### Webhook Payload

```json
{
    "event": "execution.flagged",
    "timestamp": "2026-02-11T14:32:00Z",
    "agent_id": "report-gen",
    "execution_id": "exec_8f3a2b",
    "confidence": 0.42,
    "action": "flag",
    "failure_types": ["hallucination"],
    "summary": "2 ungrounded claims detected",
    "trace_url": "https://app.agentguard.dev/trace/{execution_id}"
}
```

Webhook fires within 5s of verification completing.

### MVP Simplification

Webhook URL configured per-agent via env var or JSON config file, not a DB-backed settings UI.

---

## 5. SDK Updates

Changes to `guard.py`, `transport.py`, `models.py`.

### `GuardResult` (enriched)

```python
class GuardResult:
    output: Any                      # original output (correction comes Phase 3)
    confidence: Optional[float]      # 0-1 composite score
    action: str                      # "pass" | "flag" | "block"
    execution_id: str
    checks: Optional[Dict[str, Any]] # per-check results
```

### Sync Mode Behavior

- `watch` decorator: when `mode="sync"`, calls `SyncTransport.verify()` after the agent function returns
  - `action == "block"` → raises `AgentGuardBlockError`
  - `action == "flag"` → logs warning, returns normally
  - `action == "pass"` → returns normally
  - Result accessible via `guard.last_result`
- `trace` context manager: when `mode="sync"`, calls verify on `_finalise()`. Result via `ctx.result`
- Async telemetry still fires in sync mode — you get inline verification AND the event goes through the async pipeline

### `ThresholdConfig`

Already exists in the SDK with `pass`, `flag`, `block` fields. Phase 2 activates it — the values are sent to the Sync Gateway in the verify request.

---

## 6. Database Migrations

### Migration 005: `check_results` table

```sql
CREATE TABLE check_results (
    id SERIAL,
    execution_id VARCHAR(64) NOT NULL,
    check_type VARCHAR(32) NOT NULL,
    score DOUBLE PRECISION,
    passed BOOLEAN NOT NULL,
    details JSONB NOT NULL DEFAULT '{}',
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, timestamp)
);

SELECT create_hypertable('check_results', 'timestamp');
CREATE INDEX ix_check_results_execution_id ON check_results (execution_id);
```

### Migration 006: `alerts` table

```sql
CREATE TABLE alerts (
    alert_id VARCHAR(64) NOT NULL,
    execution_id VARCHAR(64) NOT NULL,
    agent_id VARCHAR(128) NOT NULL,
    org_id VARCHAR(64) NOT NULL DEFAULT 'default',
    alert_type VARCHAR(32) NOT NULL,
    severity VARCHAR(16) NOT NULL,
    webhook_url TEXT,
    delivered BOOLEAN NOT NULL DEFAULT FALSE,
    delivery_attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TIMESTAMPTZ,
    response_status INTEGER,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (alert_id, timestamp)
);

SELECT create_hypertable('alerts', 'timestamp');
CREATE INDEX ix_alerts_agent_id ON alerts (agent_id, timestamp);
```

### Storage Worker Update

Add a second consumer group on `executions.verified`. When receiving verified events:
- Write `check_results` rows (one per check type)
- Update execution row: set `confidence` and `action` columns

---

## 7. Dashboard Updates

### Execution Trace View — verification results panel

New section on the existing trace page showing:
- Confidence score with color-coded badge (green >= 0.8, yellow >= 0.5, red < 0.5)
- Action pill (pass/flag/block)
- Per-check breakdown: schema (pass/fail), hallucination (score + flagged claims), drift (score + explanation)
- Data from `check_results` joined on `execution_id`

### Failures Feed — new page `/agents/failures`

- Chronological table of flagged/blocked executions
- Columns: timestamp, agent, task, action, confidence, failure types
- Filterable by agent, action, time range
- Click row → trace view
- Real-time via existing WebSocket

### Fleet Health — confidence column

- `Avg Confidence` column in agent table (data from `agent_health_hourly` aggregate)
- Agent status updated: confidence < 0.5 avg → degraded

---

## 8. Integration Tests

End-to-end verification of both paths:

**Sync path test:**
SDK (sync mode) → Sync Gateway → engine runs → response with confidence/action → event emitted to Redis → storage worker writes check_results → verify DB state

**Async path test:**
SDK (async mode) → Ingestion API → executions.raw → async worker runs engine → executions.verified → storage worker writes check_results → alert service fires webhook (mock) → verify DB state + webhook received

---

## Files Summary

| Action | Location |
|---|---|
| Create | `services/verification-engine/` (package: engine + tests) |
| Create | `services/sync-gateway/app/main.py`, `routes.py` |
| Create | `services/async-worker/app/main.py`, `worker.py` |
| Create | `services/alert-service/app/main.py`, `worker.py`, `webhook.py` |
| Create | `services/migrations/alembic/versions/005_add_check_results.py` |
| Create | `services/migrations/alembic/versions/006_add_alerts.py` |
| Modify | `sdk/python/agentguard/guard.py` — sync mode verify, block/flag behavior |
| Modify | `sdk/python/agentguard/models.py` — enriched GuardResult |
| Modify | `sdk/python/agentguard/transport.py` — parse VerifyResponse into GuardResult |
| Modify | `services/storage-worker/` — consume executions.verified, write check_results |
| Modify | `nextjs-application/apps/web/` — trace verification panel, failures feed, confidence column |
| Modify | `.github/workflows/ci.yml` — add verification-engine + new services to test matrix |
