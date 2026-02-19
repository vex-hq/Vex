# Vex Platform Gaps & Feature Roadmap

**Date:** 2026-02-20
**Status:** Approved

## Context

Comprehensive gap audit of the Vex platform against competitors (Raindrop.ai, Guardrails AI, Galileo, Braintrust, Langfuse, LangSmith, Sentrial). Vex's core strength is sync verification + auto-correction cascade — no competitor has this. The gaps are in detection breadth, analytics depth, and SDK extensibility.

## Competitor Reference: Raindrop.ai ("Sentry for AI Agents")

$15M seed (Lightspeed). Key features we lack: tool loop detection, custom adaptive classifiers, natural-language guardrail definitions, failure clustering, A/B testing, PII guard, Slack alerts, semantic search. Pricing: $65/$350/custom vs Vex $79/$299/custom.

## Phase 1: Close Critical Gaps

### 1.1 Tool Loop / Cycle Detection
- New verification check in `services/verification-engine/engine/`
- Analyze the `steps` array for repeated identical tool calls, cycles, or excessive tool call count
- Configurable thresholds: `max_tool_calls`, `max_repeated_calls`
- Score: 1.0 (no loops) down to 0.0 (definite runaway loop)
- Add as 5th check in the pipeline alongside schema, hallucination, drift, coherence

### 1.2 Custom Guardrails (Rule Engine)
- New `guardrails` table: `id`, `org_id`, `agent_id` (nullable for org-wide), `rule_type` (regex, keyword, threshold, llm), `condition` (JSON), `action` (flag/block), `enabled`, `created_at`
- Rule types:
  - `regex`: match output against pattern → flag/block
  - `keyword`: block if output contains specific terms
  - `threshold`: flag if token_count > N, cost > N, latency > N
  - `llm`: natural-language rule evaluated by LLM (e.g., "block if the agent recommends a competitor")
- Evaluated after the 4 standard checks, before action routing
- Dashboard UI: CRUD for guardrails per agent or org-wide
- SDK: optional `guardrails` config to pass rule IDs

### 1.3 Slack Alert Delivery
- Implement Slack webhook delivery in `services/alert-service/`
- `SLACK_WEBHOOK_URL_{AGENT_ID}` or `SLACK_WEBHOOK_URL` env vars (same pattern as HTTP webhooks)
- Formatted Slack Block Kit message with agent name, action, confidence, failure types, link to execution
- Gated behind `plan_limits.slack_alerts` (team/enterprise only)

### 1.4 Alert Deduplication & Rate Limiting
- Window-based suppression: max 1 alert per agent per alert_type per 5-minute window
- Count suppressed alerts, include count in next delivered alert ("12 similar events in last 5 min")
- In-memory window tracking in the alert worker (Redis-backed for multi-instance)

### 1.5 Tool Calls in Relational Storage
- New `tool_calls` table: `id`, `execution_id`, `org_id`, `agent_id`, `tool_name`, `input` (JSONB), `output` (JSONB), `duration_ms`, `sequence`, `timestamp`
- TimescaleDB hypertable on `timestamp`
- Populated by storage-worker when processing raw events from S3 trace payloads
- Indexes: `(agent_id, tool_name, timestamp)`, `(org_id, timestamp)`

## Phase 2: Analytics Power

### 2.1 Per-Check Score Trends
- New materialized view: `check_score_hourly` — avg score per check_type per agent per hour
- Dashboard: line chart on agent detail page showing schema/hallucination/drift/coherence scores over time
- Refresh policy: 1 hour (same as existing materialized views)

### 2.2 Tool Usage Analytics Page
- New dashboard page: `/home/[account]/tools`
- Queries: most-used tools, tool → flag/block correlation rate, avg tool duration, tool call frequency distribution
- Requires Phase 1.5 (tool_calls table)

### 2.3 Correction Effectiveness Dashboard
- New dashboard section on agent detail: initial confidence vs post-correction confidence scatter
- Layer usage breakdown (L1/L2/L3 pie chart)
- Correction success rate trend over time
- Data source: `executions.correction_layers_used` JSONB + `executions.corrected`

### 2.4 Failure Clustering
- Group failures by: check_type + agent + time bucket
- Start with SQL-based grouping (no embeddings needed initially)
- Dashboard: "Top failure patterns this week" widget on homepage
- Future: vector embeddings on failure details for semantic clustering

### 2.5 Cost & Latency Anomaly Detection
- Z-score based alerting: compare each execution's cost/latency against agent's rolling 24h mean + stddev
- New alert types: `cost_anomaly`, `latency_anomaly`
- Configurable sensitivity (default: 3 standard deviations)
- Runs in alert-service after receiving verified events

## Phase 3: SDK & Developer Experience

### 3.1 LangChain Callback Handler
- `VexCallbackHandler(vex, agent_id)` — implements LangChain's `BaseCallbackHandler`
- Automatically captures: `on_llm_start/end`, `on_tool_start/end`, `on_chain_start/end`
- Maps to Vex `step()` calls with proper step_type
- Both Python and TypeScript

### 3.2 Middleware / Hook System
- `vex.on('block', callback)`, `vex.on('flag', callback)`, `vex.on('verify', callback)`
- Pre-send hooks: `vex.before('ingest', callback)` — transform/filter before sending
- Enables custom error handling, logging, circuit breakers

### 3.3 Sampling Configuration
- `Vex(sample_rate=0.1)` — probabilistic sampling
- `Vex(sample_fn=lambda event: event.metadata.get('important'))` — custom sampling function
- Essential for high-volume production agents

### 3.4 PII Detection Check
- New verification check: regex-based detection of emails, phone numbers, SSNs, credit cards
- Optional LLM-based detection for contextual PII (names, addresses)
- Configurable: which PII types to detect, action on detection (flag vs block)
- Can be combined with auto-correction to redact PII

### 3.5 A/B Experiment Tracking
- New fields: `experiment_id`, `variant` in execution metadata
- SDK: `vex.trace(agent_id, task, experiment='prompt-v2', variant='concise')`
- Dashboard: comparison view of two variants' confidence, action distribution, cost, latency
- Statistical significance indicator

## Execution Order

Phase 1: 1.1 → 1.3 → 1.4 → 1.5 → 1.2
Phase 2: 2.1 → 2.3 → 2.2 → 2.5 → 2.4
Phase 3: 3.3 → 3.1 → 3.2 → 3.4 → 3.5

## What Doesn't Change

- Core 4-check verification pipeline stays as-is
- 3-layer correction cascade stays as-is
- Redis Streams architecture stays as-is
- Existing SDK API surface is additive only (no breaking changes)
- Plan tier structure stays as-is (features gated by plan)

## Landing Page Updates

- Add Raindrop.ai to the competitor comparison table
- Create `/compare/raindrop` page
