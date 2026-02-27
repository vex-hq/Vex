# Ingestion API

Receives agent execution telemetry from the SDK and pushes events onto a Redis Stream for downstream processing.

## Responsibilities

- Accepts single and batch execution events via HTTP
- Validates API keys with the `ingest` scope
- Publishes events to the `executions.raw` Redis Stream
- Injects the authenticated `org_id` into each event's metadata

## Dependencies

### External
- **Redis** — produces to `executions.raw` stream
- **PostgreSQL** — read-only access to `organizations` table for API key validation

### Internal
- **shared** — `models.IngestEvent`, `models.IngestResponse`, `auth.KeyValidator`, `redis_config`

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check (verifies Redis connectivity) |
| POST | `/v1/ingest` | Ingest a single execution event (returns 202) |
| POST | `/v1/ingest/batch` | Ingest up to 50 events in one request (returns 202) |

## Authentication

All `/v1/*` endpoints require an `X-Vex-Key` header (falls back to `X-AgentGuard-Key`). The key must have the `ingest` scope.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `REDIS_URL` | No | Redis connection string (default: `redis://localhost:6379`) |
| `DATABASE_URL` | No | PostgreSQL connection string for key validation (default: local dev) |
| `SUPABASE_DATABASE_URL` | No | Supabase PostgreSQL URL for plan lookups |

## Running Locally

```bash
cd services/ingestion-api
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

## Testing

```bash
pytest tests/ -v
```
