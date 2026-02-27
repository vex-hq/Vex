# Sync Gateway

Unified API gateway for the SDK, handling synchronous verification with optional correction cascade and async event ingestion.

## Responsibilities

- Synchronous output verification via the verification engine pipeline
- Correction cascade (up to 2 attempts) for failed verifications on paid plans
- Single and batch event ingestion (same interface as ingestion-api)
- Loads per-agent and org-wide guardrail rules from PostgreSQL
- Emits events to both `executions.raw` and `executions.verified` Redis Streams
- Enforces plan-based feature gating (corrections, quotas, agent limits)
- Dynamic timeouts: 2 s for verify-only, 10 s for correction cascade

## Dependencies

### External
- **Redis** — produces to `executions.raw` and `executions.verified` streams
- **PostgreSQL** — reads `organizations` (key validation), `guardrails` (rule loading), `agents` (agent limits), `hourly_agent_stats` (quota)

### Internal
- **shared** — `models`, `auth.KeyValidator`, `plan_limits`, `redis_config`
- **verification-engine** — `pipeline.verify`, `correction.correct`, `correction.select_layer`, `models`

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check (verifies Redis connectivity) |
| POST | `/v1/verify` | Synchronous verification with optional correction cascade |
| POST | `/v1/ingest` | Ingest a single execution event (returns 202) |
| POST | `/v1/ingest/batch` | Ingest up to 50 events in one request (returns 202) |

## Authentication

- `/v1/verify` requires the `verify` scope
- `/v1/ingest` and `/v1/ingest/batch` require the `ingest` scope
- Both accept `X-Vex-Key` (or `X-AgentGuard-Key`) header

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `REDIS_URL` | No | Redis connection string (default: `redis://localhost:6379`) |
| `DATABASE_URL` | No | PostgreSQL connection string (default: local dev) |
| `SUPABASE_DATABASE_URL` | No | Supabase PostgreSQL URL for plan lookups |
| `GATEWAY_TIMEOUT_S` | No | Verify-only timeout in seconds (default: `2.0`) |
| `CORRECTION_TIMEOUT_S` | No | Correction cascade timeout in seconds (default: `10.0`) |
| `VERIFICATION_MODEL` | No | LLM model for verification checks (default: `claude-haiku-4-5-20251001`) |
| `CORRECTION_REPAIR_MODEL` | No | LLM model for Layer 1 repair (default: `gpt-4o-mini`) |
| `CORRECTION_STRONG_MODEL` | No | LLM model for Layer 2-3 correction (default: `gpt-4o`) |
| `LITELLM_API_URL` | No | LiteLLM proxy base URL |
| `LITELLM_API_KEY` | No | LiteLLM proxy API key |

## Running Locally

```bash
cd services/sync-gateway
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

## Testing

```bash
pytest tests/ -v
```
