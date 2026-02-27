# Vex Architecture

## System Overview

Vex is an event-driven microservices platform for real-time AI agent verification and correction. SDKs (Python and TypeScript) submit agent execution data through two entry paths — a synchronous verification gateway and an asynchronous ingestion API — both of which emit events to Redis Streams. Downstream consumers independently process these events for verification, persistent storage (PostgreSQL + S3), alerting (webhooks/Slack), and real-time dashboard updates via WebSocket. This architecture decouples ingestion latency from processing latency, enabling sub-second synchronous verification while supporting high-throughput async telemetry.

## Architecture Diagram

```
                           ┌──────────────────┐
                           │   SDK (Python /   │
                           │   TypeScript)     │
                           └────────┬─────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
              POST /v1/verify                 POST /v1/ingest
              (sync path)                     (async path)
                    │                               │
                    v                               v
         ┌──────────────────┐            ┌──────────────────┐
         │  sync-gateway    │            │  ingestion-api   │
         │  (FastAPI)       │            │  (FastAPI)       │
         │                  │            │                  │
         │  Runs verify +   │            │  Accepts events, │
         │  correction      │            │  emits to Redis  │
         │  inline          │            │                  │
         └───────┬──────────┘            └────────┬─────────┘
                 │                                │
                 │  ┌─────────────────────────────┘
                 │  │
                 v  v
         ┌──────────────────┐
         │  Redis Streams   │
         │                  │
         │  executions.raw  │──────────────────────────────┐
         │  executions.     │──────────┐                   │
         │    verified      │───┐      │                   │
         │  executions.     │   │      │                   │
         │    stored        │─┐ │      │                   │
         └──────────────────┘ │ │      │                   │
                              │ │      │                   │
                              │ │      │                   v
                              │ │      │          ┌──────────────────┐
                              │ │      │          │  async-worker    │
                              │ │      │          │  (Consumer)      │
                              │ │      │          │                  │
                              │ │      │          │  Reads raw,      │
                              │ │      │          │  runs verify,    │
                              │ │      │          │  emits verified  │
                              │ │      │          └──────────────────┘
                              │ │      │
                              │ │      v
                              │ │  ┌──────────────────┐
                              │ │  │  storage-worker   │
                              │ │  │  (Consumer)       │
                              │ │  │                   │
                              │ │  │  Reads raw +      │
                              │ │  │  verified,        │
                              │ │  │  persists to      │
                              │ │  │  PostgreSQL + S3,  │
                              │ │  │  emits stored     │
                              │ │  └──────────────────┘
                              │ │
                              │ v
                              │ ┌──────────────────┐
                              │ │  alert-service    │
                              │ │  (Consumer)       │
                              │ │                   │
                              │ │  Reads verified,  │
                              │ │  sends webhooks   │
                              │ │  on flag/block    │
                              │ └──────────────────┘
                              │
                              v
                    ┌──────────────────┐       ┌──────────────────┐
                    │  dashboard-api   │◄──────│  Dashboard       │
                    │  (FastAPI + WS)  │       │  (Next.js)       │
                    │                  │       │                  │
                    │  Reads stored,   │──────►│  Real-time UI    │
                    │  pushes via      │  WS   │                  │
                    │  WebSocket       │       │                  │
                    └──────────────────┘       └──────────────────┘
```

## Service Responsibility Table

| Service | Type | Purpose | Consumes | Produces |
|---------|------|---------|----------|----------|
| **sync-gateway** | FastAPI (HTTP) | Unified SDK entry point; synchronous verification with optional correction cascade (2s verify / 10s with correction) | HTTP (`/v1/verify`, `/v1/ingest`, `/v1/ingest/batch`) | Redis: `executions.raw`, `executions.verified` |
| **ingestion-api** | FastAPI (HTTP) | Async event ingestion; accepts single and batch events (up to 50) | HTTP (`/v1/ingest`, `/v1/ingest/batch`) | Redis: `executions.raw` |
| **verification-engine** | Library | 6-check verification pipeline with weighted confidence scoring | Imported by sync-gateway, async-worker | `VerificationResult` (confidence, action, checks) |
| **async-worker** | Redis Consumer | Background verification for async-ingested events; skips events already verified by sync-gateway | Redis: `executions.raw` (group: `verification-workers`) | Redis: `executions.verified` |
| **storage-worker** | Redis Consumer | Persists raw executions to S3 + PostgreSQL; updates DB with verification results | Redis: `executions.raw` (group: `storage-workers`), `executions.verified` (group: `storage-verified`) | Redis: `executions.stored` |
| **alert-service** | Redis Consumer | Delivers webhooks and records alerts for flag/block events | Redis: `executions.verified` (group: `alert-workers`) | HTTP webhooks |
| **dashboard-api** | FastAPI (HTTP + WebSocket) | Real-time dashboard backend; streams execution updates to connected clients | Redis: `executions.stored` | WebSocket broadcasts |
| **shared** | Library | Pydantic models, auth utilities, rate limiting, plan limits, Redis config | Imported by all services | -- |
| **migrations** | Alembic | Database schema management (13 migrations) | -- | PostgreSQL DDL |

## Data Flow

**Synchronous verification path** (SDK calls `/v1/verify`):

1. SDK sends execution payload to **sync-gateway** `/v1/verify` with API key.
2. sync-gateway authenticates the request, loads org-specific guardrail rules from DB, and builds a `VerificationConfig`.
3. **verification-engine** runs the 6-check pipeline inline (schema validation, hallucination detection, drift detection, coherence check, custom guardrails, tool loop detection).
4. If `correction=cascade` is set and the output fails, sync-gateway runs the 3-layer correction cascade (up to 2 attempts within a 10s budget), re-verifying after each correction.
5. sync-gateway returns the `VerifyResponse` synchronously to the SDK (confidence score, action, corrected output if applicable).
6. sync-gateway emits the event to `executions.raw` (marked `already_verified`) and the result to `executions.verified`.
7. **storage-worker** reads from `executions.raw`, persists the execution to PostgreSQL and raw payload to S3, then emits to `executions.stored`.
8. **storage-worker** also reads from `executions.verified`, updates the execution record with check results and confidence.
9. **async-worker** reads from `executions.raw`, sees `already_verified=true`, and ACKs without re-processing.
10. **alert-service** reads from `executions.verified`; if action is `flag` or `block`, delivers webhook notifications.
11. **dashboard-api** reads from `executions.stored` and pushes updates to connected Dashboard clients via WebSocket.

**Asynchronous ingestion path** (SDK calls `/v1/ingest`):

1. SDK sends execution payload to **sync-gateway** or **ingestion-api** `/v1/ingest`.
2. The service authenticates and emits to `executions.raw`.
3. **async-worker** picks up the event, runs the verification pipeline, and emits to `executions.verified`.
4. Steps 7-11 from the synchronous path follow identically.

## Verification Pipeline

The verification engine runs up to 6 checks per execution, combining deterministic and LLM-based analysis:

| # | Check | Type | Purpose |
|---|-------|------|---------|
| 1 | **Schema Validation** | Deterministic | Validates agent output against a JSON Schema definition |
| 2 | **Hallucination Detection** | LLM-based | Compares output against ground truth and conversation history to detect fabricated information |
| 3 | **Drift Detection** | LLM-based | Measures semantic divergence between the agent's output and the assigned task |
| 4 | **Coherence Check** | LLM-based | Evaluates cross-turn consistency when conversation history is provided; dynamically rebalances weights |
| 5 | **Custom Guardrails** | Hybrid | Evaluates org-defined rules: `regex`, `keyword`, `threshold` (deterministic), and `llm` (natural language). Guardrail violations with `action=block` force a block regardless of confidence |
| 6 | **Tool Loop Detection** | Deterministic | Detects repetitive tool call patterns in agent step traces |

Checks 2-5 run in parallel via `asyncio.gather`. Each check produces a score (0.0-1.0) and pass/fail. A weighted composite confidence score determines the final action:

- **pass**: confidence >= `pass_threshold` (default 0.80)
- **flag**: confidence >= `flag_threshold` (default 0.50)
- **block**: confidence < `flag_threshold`, or forced by guardrail violation

### Correction Cascade

When verification fails and `correction=cascade` is enabled (paid plans only), the sync-gateway runs a 3-layer graduated correction cascade:

| Layer | Name | Model | Strategy |
|-------|------|-------|----------|
| 1 | **Repair** | `gpt-4o-mini` | Surgical fix of specific errors (schema, format) |
| 2 | **Constrained Regeneration** | `gpt-4o` | Fresh output generation with constraints; does not see failed output to avoid anchoring |
| 3 | **Full Re-prompt** | `gpt-4o` | Regeneration with explicit failure feedback; last resort |

The cascade makes up to 2 correction attempts. After each correction, the output is re-verified. If no attempt reaches "pass", the best improvement over the initial confidence is accepted. Layer selection starts based on the failure severity and escalates on each failed attempt.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API Services | FastAPI (Python 3.11+) |
| Message Broker | Redis Streams (consumer groups for parallel independent processing) |
| Database | PostgreSQL (Neon) with Alembic migrations |
| Object Storage | S3-compatible (Cloudflare R2) |
| Dashboard Frontend | Next.js (Turborepo), React 19, pnpm |
| LLM Integration | OpenAI API (gpt-4o, gpt-4o-mini) |
| Auth | API key authentication with org-level scoping, plan-based feature gating |
| Data Models | Pydantic v2 (shared across all services) |
| Containerization | Docker |

## Infrastructure

| Component | Provider |
|-----------|----------|
| Backend Services | Railway |
| Dashboard | Vercel |
| PostgreSQL | Neon (serverless) |
| Object Storage | Cloudflare R2 |
| Redis | Railway (managed) |

## Repository Structure

```
vex/                              # Monorepo root (AGPL-3.0)
├── Dashboard/                    # Git submodule → Vex-AI-Dev/Vex-Dashboard (AGPL-3.0)
│   └── (Next.js app)            #   Turborepo, React 19, pnpm
├── sdk/
│   ├── python/                   # Git submodule → Vex-AI-Dev/Python-SDK (Apache-2.0)
│   └── typescript/               # Git submodule → Vex-AI-Dev/Typescript-sdk (Apache-2.0)
├── services/                     # Backend microservices (AGPL-3.0)
│   ├── sync-gateway/             #   Unified SDK entry, sync verification + correction
│   ├── ingestion-api/            #   Async event ingestion
│   ├── verification-engine/      #   6-check verification pipeline (library)
│   ├── async-worker/             #   Background verification consumer
│   ├── storage-worker/           #   Persistence consumer (PostgreSQL + S3)
│   ├── alert-service/            #   Webhook/Slack alerting consumer
│   ├── dashboard-api/            #   Real-time WebSocket backend
│   ├── shared/                   #   Pydantic models, auth, rate limiting
│   └── migrations/               #   Alembic database migrations
│       └── alembic/
│           └── versions/         #   13 migration scripts
├── docs/
│   └── plans/                    #   Design documents and implementation plans
└── ARCHITECTURE.md               #   This file
```

## Reference

Detailed design documents and implementation plans are available in [`docs/plans/`](docs/plans/). Key documents include:

- **Architecture Design**: `2026-02-10-agentguard-architecture-design.md`
- **Phase 1 -- Foundation**: `2026-02-10-phase1-foundation.md`
- **Phase 2 -- Core Reliability**: `2026-02-11-phase2-core-reliability.md`
- **Phase 3 -- Correction Cascade**: `2026-02-11-phase3-correction-cascade.md`
- **API Key Management**: `2026-02-12-api-key-management.md`
- **Production Hardening**: `2026-02-15-production-hardening-design.md`
- **TypeScript SDK Design**: `2026-02-15-typescript-sdk-design.md`
- **Monetization**: `2026-02-19-monetization-design.md`
- **Tool Loop Detection**: `2026-02-20-tool-loop-detection.md`
- **Licensing**: `2026-02-22-licensing-design.md`
