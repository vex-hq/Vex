# AgentGuard Architecture Design

**Version:** 1.0
**Date:** February 10, 2026
**Status:** Draft
**Authors:** Abhishek Singh, Karim (TBC)
**Company:** Oppla.ai

---

## 1. Overview

AgentGuard is the runtime reliability layer for AI agents in production. It observes every agent execution, verifies every output, and corrects agents when they fail — before bad results reach end users.

This document defines the technical architecture for AgentGuard's MVP and near-term roadmap, covering system components, data flow, storage, deployment, and phased delivery.

### Key Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Infrastructure | Hybrid — managed AWS services, all containerized | MVP speed without lock-in. Self-hosted story is a container handoff. |
| Verification mode | Dual-mode — sync for blocking, async for observability | Schema checks always sync (<50ms). Semantic checks configurable per agent. |
| LLM strategy | Tiered — small model first, large model for ambiguous cases | Controls cost (medium-severity risk). ~80% of checks resolved by small model. |
| Data storage | PostgreSQL/TimescaleDB + S3 | Time-series queries for dashboards. S3 for large trace payloads. Most portable for self-hosted. |
| Correction strategy | 3-layer Correction Cascade (Repair, Constrained Regen, Re-prompt) | Proportional response — cheapest fix first, escalate only when needed. |
| Correction transparency | Configurable — opaque by default, transparent opt-in | Simple DX by default. Power users get full audit trail. |
| Compute | ECS Fargate | Containerized, auto-scaling, no cluster ops. Not Lambda (cold starts kill latency). Not EKS (overkill for MVP). |
| Event bus | Redis 7 Streams | Lightweight, persistent, consumer groups. Migration path to Kafka at scale. |

---

## 2. System Architecture

### 2.1 High-Level Topology

Five core services communicating through a central event bus, with two paths through the system (sync and async).

```
┌─────────────────────────────────────────────────────────────┐
│                      Agent Application                       │
│                    (Customer's Code)                          │
│                          │                                    │
│                   ┌──────┴──────┐                             │
│                   │ AgentGuard  │                             │
│                   │    SDK      │                             │
│                   └──────┬──────┘                             │
└──────────────────────────┼───────────────────────────────────┘
                           │
              ┌────────────┼────────────────┐
              ▼                             ▼
     ┌────────────────┐           ┌──────────────────┐
     │  Ingestion API  │           │  Sync Verification│
     │  (Async Path)   │           │  Gateway (Sync)   │
     └───────┬────────┘           └────────┬─────────┘
             │                             │
             ▼                             ▼
     ┌───────────────────────────────────────────┐
     │            Event Bus (Redis Streams)       │
     └──────┬──────────┬──────────┬──────────────┘
            ▼          ▼          ▼
  ┌──────────────┐ ┌────────┐ ┌───────────┐
  │ Verification │ │  Alert │ │ Correction│
  │   Engine     │ │Service │ │  Cascade  │
  └──────┬───────┘ └────────┘ └───────────┘
         │
         ▼
  ┌──────────────────────────────────┐
  │  Data Layer                       │
  │  PostgreSQL/TimescaleDB + S3      │
  └──────────────────────────────────┘
         │
         ▼
  ┌──────────────────────────────────┐
  │  Dashboard (React + WebSocket)    │
  └──────────────────────────────────┘
```

### 2.2 Two Paths Through the System

**Sync path:** SDK calls the Sync Verification Gateway directly. Schema validation runs inline (<50ms). If semantic checks are enabled for this agent, they run in-process (~200-500ms). Correction Cascade triggers if needed. Result (pass/flag/block + optional corrected output + confidence score) returns to SDK before the agent call returns to the caller.

**Async path:** SDK fires telemetry to the Ingestion API via non-blocking HTTP POST and returns immediately to the caller. The Async Verification Worker picks up the event from Redis Streams, runs all checks, writes results. Dashboard updates via WebSocket. Alerts fire if thresholds are breached. No blocking, no correction — observe only.

---

## 3. SDK Architecture

### 3.1 Design Principle

The SDK must feel like adding a decorator, not adopting a framework. 3 lines of code, zero changes to agent logic. Integration time target: <15 minutes (stretch: <5 minutes).

### 3.2 Languages

- Python (primary, ships Phase 1)
- TypeScript (ships Phase 3)

### 3.3 Integration Patterns

Three universal patterns that work with any agent framework (LangChain, CrewAI, custom, raw API calls):

```python
from agentguard import AgentGuard, GuardConfig

guard = AgentGuard(
    api_key="ag_...",
    config=GuardConfig(
        mode="sync",                    # or "async"
        correction="cascade",           # or "none"
        transparency="opaque",          # or "transparent"
        confidence_threshold={
            "pass": 0.8,
            "flag": 0.5,
            "block": 0.3
        }
    )
)

# Option 1: Decorator (simplest)
@guard.watch(agent_id="support-bot", task="Answer customer billing questions")
def handle_support(query: str) -> str:
    return my_agent.run(query)

# Option 2: Context manager (more control)
with guard.trace(agent_id="data-enricher", task="Enrich company records") as trace:
    result = my_agent.run(input_data)
    trace.set_ground_truth(source_documents)
    trace.set_schema(output_schema)
    trace.record(result)

# Option 3: Explicit wrap (framework-agnostic escape hatch)
result = guard.run(
    agent_id="report-gen",
    task="Generate quarterly financial summary",
    fn=lambda: my_agent.run(query),
    ground_truth=source_docs,
    schema=report_schema
)
```

### 3.4 Auto-Captured Data (P0-2)

- Input/output payloads
- Execution ID (UUID) + timestamp
- Agent ID (developer-defined)
- Latency (wall clock)
- Token count (intercepted from LLM provider response headers/metadata)
- Intermediate steps + tool calls (via hooks into framework callback systems, or manual `trace.step()` for custom agents)

### 3.5 Local Processing (no network round-trip)

- Schema validation against JSON Schema definitions (<50ms)
- Input/output size checks
- Basic format validation (valid JSON, within token limits)

### 3.6 Network Behavior

- **Sync mode:** POST to `/v1/verify`, wait for response. Timeout: 2s hard cap.
- **Async mode:** Non-blocking POST to `/v1/ingest`. Local buffer + background thread, flushes every 1s or at 50 events.
- **Batch endpoint:** `POST /v1/ingest/batch` accepts up to 50 events per request for buffer flushes.

### 3.7 Return Object

```python
class GuardResult:
    output: Any              # original or corrected output
    confidence: float        # 0-1 composite score
    action: str              # "pass" | "flag" | "block"
    corrections: list | None # None if opaque mode
    execution_id: str        # for trace lookup in dashboard
    verification: dict       # detailed check results (if transparent)
```

### 3.8 Framework Integration Strategy

No framework-specific adapters in v1. The three universal integration patterns work with anything. Framework-specific auto-instrumentation (auto-detect LangChain callbacks, CrewAI hooks) comes as P1 convenience.

---

## 4. Verification Engine

The core intelligence of AgentGuard. Implemented as a shared Python library used by both the Sync Verification Gateway and the Async Verification Worker.

### 4.1 Verification Pipeline

Runs all checks and collects all failures (does not short-circuit on first failure):

```
Agent Output
    │
    ▼
┌─────────────────────┐
│ 1. Schema Validation │  ← Deterministic, <50ms
└─────────┬───────────┘
          ▼
┌─────────────────────────┐
│ 2. Hallucination Check   │  ← Tiered LLM, ~100-300ms
└─────────┬───────────────┘
          ▼
┌─────────────────────────┐
│ 3. Task Drift Detection  │  ← Tiered LLM, ~100-300ms
└─────────┬───────────────┘    (runs parallel with #2)
          ▼
┌─────────────────────────┐
│ 4. Confidence Scoring    │  ← Weighted composite
└─────────┬───────────────┘
          ▼
    Route to Action
```

Hallucination check and task drift detection run in parallel (they are independent) reducing worst-case semantic check latency from ~600ms to ~300ms.

### 4.2 Schema Validation

- Deterministic JSON Schema validation
- Checks required fields, types, formats, value ranges
- No LLM needed
- Produces binary pass/fail + list of specific violations
- Runs locally in SDK (sync mode) and server-side (async mode)

### 4.3 Hallucination Detection (Tiered LLM)

**Tier 1 (fast model — Haiku/Flash class):**
- Extract claims and entities from the agent's output
- Compare against provided ground truth sources
- Flag any claim with no supporting evidence in sources
- Catches ~80% of hallucinations

**Tier 2 (larger model — only when Tier 1 confidence is 0.3-0.7):**
- Deeper semantic analysis: "Is claim X supported by source Y? Explain your reasoning."
- Resolves ambiguous cases where Tier 1 is uncertain

**Output:** List of flagged claims with grounding status (grounded / ungrounded / ambiguous) + evidence references.

### 4.4 Task Drift Detection (Tiered LLM)

**Tier 1 (fast model):**
- Given task description and agent output, score 0-1: "Does this output address the specified task?"
- Semantic similarity + intent matching

**Tier 2 (larger model — only when ambiguous):**
- "The task was X. The output discusses Y. Is this a valid response or has the agent drifted?"

**Output:** Drift score (0-1) + explanation of detected drift.

### 4.5 Confidence Scoring

Weighted composite of all verification checks:

```
confidence = (
    w1 * schema_score +        # 1.0 if pass, 0.0 if fail
    w2 * hallucination_score +  # % of claims grounded
    w3 * drift_score            # 0-1 from drift detection
)
```

Default weights: `w1=0.3, w2=0.4, w3=0.3`

Hallucination weighted highest — fabricated data is the highest-risk failure mode. Weights configurable per agent.

Confidence score computed within 200ms of checks completing (P0-10).

### 4.6 Shared Library Structure

```
agentguard-engine/
├── schema_validator.py
├── hallucination_detector.py
├── drift_detector.py
├── confidence_scorer.py
├── correction_cascade.py
└── llm_client.py              # tiered routing via LiteLLM
```

Used identically by the Sync Gateway (in-process) and the Async Worker (as consumer). Ensures both paths produce identical verification results.

---

## 5. Correction Cascade

A 3-layer graduated self-correction system that applies the cheapest fix first and escalates only when necessary. Modeled as a proportional immune response.

### 5.1 Routing Logic

The Verification Engine's output (failure type + severity + confidence score) determines which correction layer is invoked:

| Signal | Layer Triggered |
|---|---|
| Schema violation (missing/wrong fields) | Layer 1 — Repair |
| Minor hallucination (wrong number, extra entity) | Layer 1 — Repair |
| Partial hallucination + some grounded content | Layer 2 — Constrained Regen |
| Task drift (close but off-topic) | Layer 2 — Constrained Regen |
| Confidence < 0.3 (fundamentally broken) | Layer 3 — Full Re-prompt |
| Multiple failure types simultaneously | Layer 3 — Full Re-prompt |

### 5.2 Layer Definitions

| Layer | What It Does | When | LLM Cost |
|---|---|---|---|
| **Layer 1: Output Repair** | Small model patches specific issues in the existing output (fill missing fields, remove ungrounded claims, fix format). Output is 90% right — don't throw it away. | Schema violations, minor hallucinations | ~500 tokens |
| **Layer 2: Constrained Regeneration** | Re-run the agent with injected guardrails derived from the failure: schema pinned as constraint, grounding sources injected explicitly, task intent restated. Narrows the solution space. | Partial hallucination, mild task drift | 1x agent cost |
| **Layer 3: Full Re-prompt** | Re-run from scratch with explicit failure feedback: "You did X, that's wrong because Y, here's what you should do." Nuclear option for fundamentally broken outputs. | Confidence < 0.3, multiple failure types | 1x agent cost + prompt overhead |

### 5.3 Escalation Flow

```
confidence < pass_threshold?
    │
    ▼
┌──────────────────────────────────────┐
│ Route by failure type + severity      │
│ → Select correction Layer N          │
└──────────────────┬───────────────────┘
                   ▼
         ┌─────────────────┐
         │ Run correction   │
         │ Layer N          │
         └────────┬────────┘
                  ▼
         ┌─────────────────┐
         │ Re-verify output │ ← Full pipeline, no trust
         └────────┬────────┘
                  │
           Pass? ─┼──► Return corrected output
                  │
           Fail? ─┼──► Escalate to Layer N+1
                  │
         Max retries (2)?
                  │
           Yes ──► Block + Alert (needs human attention)
```

Every corrected output goes back through the full verification pipeline. The correction itself could hallucinate or drift. The cascade never trusts its own corrections blindly.

### 5.4 Transparency Modes

- **Opaque (default):** Caller receives clean output + confidence score. No indication that corrections were applied. Simpler developer experience.
- **Transparent (opt-in):** Caller receives full correction metadata — which layer ran, what changed, before/after confidence scores, specific changes made. For teams that need audit trails.

Configured per-agent via SDK config: `transparency="opaque"` or `transparency="transparent"`.

---

## 6. Ingestion API (Async Path)

Lightweight, high-throughput HTTP service. Single responsibility: accept telemetry, validate minimally, push to event bus.

### 6.1 Endpoints

- `POST /v1/ingest` — Single execution event
- `POST /v1/ingest/batch` — Up to 50 events per request

### 6.2 Processing Flow

```
1. Validate API key (X-AgentGuard-Key header)
2. Validate payload schema
3. Assign execution_id if not present
4. Push to Redis Stream (topic: executions.raw)
5. Return 202 Accepted + execution_id
```

### 6.3 Design Constraints

- No business logic — dumb pipe. Keeps it fast and horizontally scalable.
- Payload size limit: 1MB per execution. Larger payloads upload to S3 and are replaced with a reference URI.
- Authentication: API keys scoped to organization.
- Rate limiting: 10K events/min per org (configurable).

---

## 7. Sync Verification Gateway

Latency-critical path. Receives execution payload, runs full verification in-process, triggers Correction Cascade if needed, returns verdict.

### 7.1 Endpoint

- `POST /v1/verify`

### 7.2 Processing Flow

```
1. Validate API key
2. Run Verification Engine (in-process)
   ├── Schema check (<50ms)
   ├── Hallucination check (~100-300ms)  ┐
   └── Task drift check (~100-300ms)     ┘ parallel
3. Compute confidence score
4. If below threshold → Trigger Correction Cascade
   └── Re-verify corrected output
5. Emit event to Redis Stream (for dashboard + storage)
6. Return verdict to SDK
```

### 7.3 Response Format

```json
{
    "execution_id": "exec_8f3a2b",
    "confidence": 0.87,
    "action": "pass",
    "output": "<original or corrected>",
    "corrections": ["..."] ,
    "checks": {
        "schema": { "pass": true },
        "hallucination": { "score": 0.92, "flagged_claims": [] },
        "drift": { "score": 0.85, "explanation": "" }
    }
}
```

### 7.4 Key Design Choices

- **Verification Engine runs in-process** — no separate service call. Avoids network hop latency on critical path.
- **Hallucination + drift checks run in parallel** — independent checks, no reason to serialize.
- **2-second hard timeout** — if verification hasn't completed (e.g., LLM provider slow), return original output with `action: "pass"` and `confidence: null`, flag for async re-verification. Never block the customer's agent indefinitely.
- **Emits to Redis Stream after responding** — dashboard, storage, and alert service still receive the data.

---

## 8. Data Layer

### 8.1 PostgreSQL + TimescaleDB (Structured Data)

```
organizations
├── org_id (PK)
├── name
├── api_keys
└── plan

agents
├── agent_id (PK)
├── org_id (FK)
├── name
├── task
└── config (thresholds, mode, schema — JSONB)

executions (TimescaleDB hypertable)
├── execution_id (PK)
├── agent_id (FK)
├── timestamp
├── confidence
├── action (pass/flag/block)
├── latency_ms
├── token_count
├── cost_estimate
├── correction_layers_used
├── trace_payload_ref (S3 URI)
└── status

check_results (TimescaleDB hypertable)
├── execution_id (FK)
├── check_type (schema/hallucination/drift)
├── score
├── pass (boolean)
├── details_json
└── timestamp

alerts
├── alert_id (PK)
├── execution_id (FK)
├── agent_id (FK)
├── type
├── severity
├── delivered (boolean)
├── webhook_response
└── timestamp

human_reviews (for v2 self-learning)
├── execution_id (FK)
├── reviewer
├── verdict (true_positive/false_positive)
├── notes
└── timestamp
```

### 8.2 Continuous Aggregates

Pre-computed rollups updated automatically by TimescaleDB. Powers the fleet dashboard without expensive queries.

```sql
CREATE MATERIALIZED VIEW agent_health_hourly AS
SELECT
    agent_id,
    time_bucket('1 hour', timestamp) AS hour,
    COUNT(*) AS execution_count,
    AVG(confidence) AS avg_confidence,
    COUNT(*) FILTER (WHERE action = 'pass') AS pass_count,
    COUNT(*) FILTER (WHERE action = 'flag') AS flag_count,
    COUNT(*) FILTER (WHERE action = 'block') AS block_count,
    SUM(token_count) AS total_tokens,
    SUM(cost_estimate) AS total_cost,
    AVG(latency_ms) AS avg_latency
FROM executions
GROUP BY agent_id, hour;
```

### 8.3 Retention Policies

- Raw execution data: 90 days, then auto-dropped
- Continuous aggregates: retained indefinitely
- S3 trace payloads: move to Glacier after 6 months

### 8.4 S3 (Trace Payload Storage)

**Path structure:**
```
s3://agentguard-traces/{org_id}/{agent_id}/{date}/{execution_id}.json
```

**Payload contents:**
```json
{
    "execution_id": "...",
    "input": {},
    "output": {},
    "corrected_output": {},
    "intermediate_steps": [],
    "ground_truth": {},
    "verification_details": {
        "schema": {},
        "hallucination": {
            "claims": [],
            "grounding_results": []
        },
        "drift": {}
    },
    "correction_history": [
        {
            "layer": 1,
            "action": "repair",
            "input_confidence": 0.45,
            "output_confidence": 0.82,
            "changes": []
        }
    ]
}
```

### 8.5 Data Flow: Event Bus to Storage

```
Redis Stream (executions.verified)
    │
    ▼
┌──────────────────────┐
│ Storage Worker        │
│ 1. Write payload → S3 │
│ 2. Write metadata →   │
│    PostgreSQL          │
│ 3. ACK event          │
└──────────────────────┘
```

If the worker crashes mid-write, Redis retains the unacknowledged event and another worker picks it up. No data loss.

---

## 9. Dashboard

React SPA with three primary views. Real-time updates via WebSocket.

### 9.1 Fleet Health View (Landing Page)

For engineering managers at morning standup (P0-4).

- Fleet summary cards: active agents, total executions, pass rate, total cost
- Agent table: name, status (healthy/degraded/failing), pass rate, avg confidence, execution count
- Confidence trend chart (all agents, time-selectable)
- Agent status derived from rolling 1-hour pass rate: >90% healthy, 70-90% degraded, <70% failing
- Data sourced from TimescaleDB continuous aggregates — loads in <2s
- WebSocket pushes updates every 10s

### 9.2 Execution Trace View (Debugging)

For platform engineers diagnosing failures (P0-5).

- Execution metadata: agent, timestamp, latency, tokens
- Confidence score with visual indicator and action taken
- Full input/output display
- Step-by-step timeline (tool calls, LLM steps) with expandable detail
- Verification results: per-check pass/fail with specific failure reasons
- Correction history: layer used, changes made, before/after confidence
- Diff view for original vs. corrected output
- Trace payload loaded on-demand from S3

### 9.3 Failures Feed (Ops)

For DevOps/SRE monitoring (P0-6).

- Chronological list of flagged and blocked executions
- Each entry: severity, timestamp, agent name, failure type, confidence score, summary
- Filterable by agent, failure type, severity, time range
- Real-time via WebSocket — failures appear within 10s
- Clickable rows open full trace view

### 9.4 Tech Stack

- React + TypeScript
- Recharts or Tremor for charts
- Native WebSocket for real-time updates
- Hosted on CloudFront + S3 static hosting

---

## 10. Alert Service

Separate lightweight service subscribed to Redis Stream topic `executions.alerts`.

### 10.1 Processing Flow

```
1. Read alert event from Redis Stream
2. Look up agent's webhook config
3. Fire webhook POST
4. Log delivery status to DB
5. Retry on failure (3x, exponential backoff)
```

### 10.2 Webhook Payload (P0-13)

```json
{
    "event": "execution.blocked",
    "timestamp": "2026-02-10T14:32:00Z",
    "agent_id": "report-gen",
    "execution_id": "exec_8f3a2b",
    "confidence": 0.23,
    "action": "block",
    "failure_types": ["hallucination", "schema"],
    "summary": "3 fabricated claims detected, correction cascade exhausted after 2 retries",
    "trace_url": "https://app.agentguard.dev/trace/exec_8f3a2b",
    "corrections_attempted": [
        {"layer": 1, "result": "failed", "post_confidence": 0.31},
        {"layer": 3, "result": "failed", "post_confidence": 0.28}
    ]
}
```

Webhook fires within 5s of block/flag decision (P0-13).

### 10.3 P1 Extension

Slack and PagerDuty integrations are additional delivery adapters in the same service. Same event, different output format. No changes to upstream components.

---

## 11. Deployment Architecture

### 11.1 AWS Production (MVP)

```
┌─────────────────────────────────────────────────────────────┐
│                     AWS (MVP Deployment)                      │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐     │
│  │              ECS Fargate (Containerized)              │     │
│  │                                                       │     │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │     │
│  │  │ Ingestion API│  │Sync Verify   │  │  Alert     │ │     │
│  │  │  (2 tasks)   │  │Gateway       │  │  Service   │ │     │
│  │  │              │  │ (2 tasks)    │  │  (1 task)  │ │     │
│  │  └──────────────┘  └──────────────┘  └────────────┘ │     │
│  │                                                       │     │
│  │  ┌──────────────┐  ┌──────────────┐                  │     │
│  │  │Async Verify  │  │Storage       │                  │     │
│  │  │Worker        │  │Worker        │                  │     │
│  │  │ (2 tasks)    │  │ (1 task)     │                  │     │
│  │  └──────────────┘  └──────────────┘                  │     │
│  └─────────────────────────────────────────────────────┘     │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ ElastiCache  │  │ RDS Postgres │  │ S3               │   │
│  │ (Redis 7)    │  │ + TimescaleDB│  │ agentguard-traces│   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ CloudFront + S3 Static Hosting (Dashboard)            │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                               │
│  ┌──────────────┐                                            │
│  │ ALB          │ → /v1/ingest  → Ingestion API              │
│  │              │ → /v1/verify  → Sync Gateway               │
│  │              │ → /ws         → WebSocket handler          │
│  └──────────────┘                                            │
└─────────────────────────────────────────────────────────────┘
```

### 11.2 Why ECS Fargate

- **Not Lambda:** Sync Gateway needs persistent connections to Redis and Postgres. Cold starts kill the latency budget. WebSocket support is awkward.
- **Not EKS:** Overkill for MVP with 15-20 design partners. Significant operational overhead.
- **Fargate:** Containerized (portable), auto-scaling, no cluster management, per-second billing.

### 11.3 Auto-Scaling Rules

| Service | Scale On | Target |
|---|---|---|
| Ingestion API | Request count | 1000 req/s per task |
| Sync Gateway | Request count + latency | p99 < 2s |
| Async Verify Worker | Redis Stream lag | < 100 unprocessed events |
| Storage Worker | Redis Stream lag | < 100 unprocessed events |

### 11.4 Self-Hosted Story

Every service is a Docker container. Local development uses `docker-compose.yml`. When enterprise customers need self-hosted:
- Hand them `docker-compose.yml` + Helm chart
- S3 → MinIO (S3-compatible)
- ElastiCache → self-hosted Redis
- RDS → self-hosted PostgreSQL + TimescaleDB
- Same containers, different infrastructure targets

---

## 12. Tech Stack Summary

| Layer | Technology | Rationale |
|---|---|---|
| SDK | Python (primary), TypeScript (Phase 3) | Python dominates AI/ML. TS for Node agent teams. |
| Ingestion API | FastAPI (Python) | Async-native, fast, auto-generates OpenAPI docs. Same language as SDK. |
| Sync Gateway | FastAPI (Python) | Shares verification engine code as internal package. |
| Verification Engine | Python library (internal) | Shared between Gateway + Async Worker. |
| LLM Client | LiteLLM | Unified interface to Haiku/Flash/GPT-4o-mini. Swap models without code changes. |
| Event Bus | Redis 7 Streams | Lightweight, persistent, consumer groups. Kafka migration path. |
| Database | PostgreSQL 16 + TimescaleDB | Time-series queries, continuous aggregates, portable. |
| Object Store | S3 (MinIO for self-hosted) | Trace payloads. S3-compatible API everywhere. |
| Dashboard | React + TypeScript | Standard. Large talent pool. |
| Charts | Recharts or Tremor | Lightweight, React-native. |
| Real-time | WebSocket (FastAPI native) | Dashboard live updates. |
| API Auth | API keys (SDK), JWT (Dashboard) | API keys for M2M, JWT for user sessions. |
| IaC | Terraform | Reproducible environments from day 1. |
| CI/CD | GitHub Actions | Standard, free at this scale. |
| Containers | Docker + docker-compose (dev), ECS Fargate (prod) | Portable. Same containers everywhere. |
| Internal Monitoring | CloudWatch + Sentry | Monitor AgentGuard itself. |

---

## 13. MVP Phasing

### Phase 1: Foundation (Weeks 1-3)

**Goal:** Get the SDK into design partner hands. Pure observability — no verification yet.

**Build:**
- SDK (Python): decorator, context manager, explicit wrap, auto-capture, local schema validation, async telemetry buffer
- Ingestion API: POST /v1/ingest + /v1/ingest/batch, API key auth, Redis Stream producer
- Storage Worker: Redis consumer, S3 write, PostgreSQL write
- Dashboard (minimal): fleet list, execution list, basic trace view
- Infrastructure: Terraform, docker-compose, CI/CD, DB migrations

**Ship:** Design partners instrument agents and see traces in the dashboard.

### Phase 2: Core Reliability (Weeks 4-6)

**Goal:** Real-time verification with threshold-based actions.

**Build:**
- Verification Engine (shared library): schema validator, hallucination detector (tiered), drift detector (tiered), confidence scorer, LLM client
- Sync Verification Gateway: POST /v1/verify, in-process engine, parallel checks, 2s timeout
- Async Verification Worker: Redis consumer, verification engine, results to DB + alert events
- SDK updates: sync mode, threshold config, GuardResult return
- Alert Service: Redis consumer, webhook delivery + retry, delivery logging
- Dashboard updates: verification results in traces, failures feed, confidence scores, agent status

**Ship:** Design partners get real-time verification, threshold-based actions, webhook alerts.

### Phase 3: Self-Correction (Weeks 7-8)

**Goal:** Full reliability layer — observe, verify, correct.

**Build:**
- Correction Cascade: Layer 1 (repair), Layer 2 (constrained regen), Layer 3 (full re-prompt), escalation logic, re-verification, max retry enforcement
- SDK updates: correction config, transparency config, correction metadata in GuardResult, TypeScript SDK
- Dashboard updates: correction history in traces, before/after diff, correction success rates, polish

**Ship:** Complete product. Design partners experience the full reliability layer.

### Phase 4: Learn & Iterate (Weeks 9+)

**Based on design partner feedback:**
- Custom verification rules (P1-4)
- Slack/PagerDuty integration (P1-1)
- Cost tracking dashboard (P1-2)
- Confidence trend charts + anomaly detection (P1-3)
- Execution replay (P1-5)
- Begin v2 planning (pipeline monitoring, self-learning)

---

## 14. Open Decisions Resolved

| Question from PRD | Decision | Rationale |
|---|---|---|
| Sync vs. async verification | Dual-mode. Schema always sync. Semantic checks configurable per agent. | Flexibility without forcing latency on all agents. |
| Which LLM for semantic checks | Tiered. Small model (Haiku/Flash) for first pass. Large model only for ambiguous cases (confidence 0.3-0.7). | Controls cost. ~80% resolved by small model. |
| SDK-first or dashboard-first | SDK-first with minimal trace viewer (Phase 1). Full dashboard builds incrementally. | Gets data flowing from design partners immediately. |

## 15. Open Decisions Remaining

| Question | Context | Recommendation |
|---|---|---|
| Pricing model | Per-execution, per-agent, per-seat, or platform fee | Validate through design partner interviews during Phase 1-2 |
| Open-source strategy | SDK open-source (Langfuse model) vs. proprietary | Open-source SDK, managed dashboard. Drives adoption. |
| Dashboard primary persona | Developer debugging vs. manager checking fleet health | Design for developer first (trace view), manager second (fleet view) |
| Self-hosted timeline | When to offer on-prem | Architecture supports it from day 1. Build the offering when enterprise demand materializes. |
| Product name | AgentGuard is working name | Validate with users. Check domain/trademark. |

---

## Appendix A: PRD Requirement Traceability

| PRD Requirement | Architecture Component | Phase |
|---|---|---|
| P0-1: SDK wraps any agent call | SDK (3 integration patterns) | Phase 1 |
| P0-2: Auto-captures all data points | SDK auto-capture | Phase 1 |
| P0-3: Framework-agnostic | Universal patterns, no adapters | Phase 1 |
| P0-4: Fleet health dashboard (<2s load) | Dashboard + TimescaleDB aggregates | Phase 1 (minimal), Phase 2 (full) |
| P0-5: Execution trace view (<1s load) | Dashboard + S3 lazy load | Phase 1 |
| P0-6: Failures feed (within 10s) | Dashboard + WebSocket | Phase 2 |
| P0-7: Hallucination detection (>80% precision) | Verification Engine (tiered) | Phase 2 |
| P0-8: Schema validation (<50ms) | SDK local + Verification Engine | Phase 1 (local), Phase 2 (server) |
| P0-9: Task drift detection (>75% precision) | Verification Engine (tiered) | Phase 2 |
| P0-10: Confidence scoring (<200ms) | Confidence Scorer | Phase 2 |
| P0-11: Threshold-based actions (<100ms) | SDK + Sync Gateway | Phase 2 |
| P0-12: Self-correction (max 2 retries) | Correction Cascade | Phase 3 |
| P0-13: Webhook alerts (<5s) | Alert Service | Phase 2 |
