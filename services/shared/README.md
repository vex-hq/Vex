# Shared

Common library providing Pydantic models, API key authentication, plan limits, and Redis configuration shared across all backend services.

## Responsibilities

- Defines the canonical Pydantic models for the SDK-to-backend API contract (`IngestEvent`, `VerifyRequest`, `VerifyResponse`, etc.)
- Provides `KeyValidator` for SHA-256 hash-based API key authentication with:
  - In-memory cache (60 s TTL)
  - Per-key scope enforcement (`ingest`, `verify`, `read`)
  - Sliding-window rate limiting (requests per minute)
  - Monthly quota enforcement against `hourly_agent_stats`
  - Per-plan agent limit enforcement
  - Batched `last_used_at` updates
  - Optional Supabase integration for plan resolution
- Defines plan-level limits and feature flags for all pricing tiers (`free`, `starter`, `pro`, `team`, `enterprise`)
- Provides shared Redis client configuration for resilient stream connections

## Key Modules

| Module | Description |
|--------|-------------|
| `shared/models.py` | Pydantic models: `IngestEvent`, `VerifyRequest`, `VerifyResponse`, `CheckResult`, `StepRecord`, `GuardrailRule`, etc. |
| `shared/auth.py` | `KeyValidator` class and `AuthError` exception for API key validation |
| `shared/plan_limits.py` | `PlanConfig` dataclass and `PLAN_LIMITS` dict with per-tier quotas, rate limits, feature flags, and retention days |
| `shared/redis_config.py` | `REDIS_CLIENT_OPTIONS` dict with timeout, keepalive, and retry settings |

## Dependencies

### External
- **SQLAlchemy** — database queries for key validation and quota checks
- **psycopg2** — PostgreSQL driver
- **Pydantic** — model definitions and validation

### Internal
- None (this is a leaf dependency)

## Used By

All backend services depend on this library:
- ingestion-api
- sync-gateway
- async-worker
- storage-worker
- dashboard-api
- alert-service

## Installation

```bash
cd services/shared
pip install -e ".[dev]"
```

## Testing

```bash
pytest tests/ -v
```
