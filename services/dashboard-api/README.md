# Dashboard API

Real-time WebSocket API that streams execution updates to connected dashboard clients.

## Responsibilities

- Subscribes to the `executions.stored` Redis Stream (using XREAD, not a consumer group)
- Broadcasts `execution.new` events to all connected WebSocket clients
- Manages WebSocket connection lifecycle with automatic cleanup of disconnected clients

## Dependencies

### External
- **Redis** — reads from `executions.stored` stream (non-destructive XREAD)

### Internal
- None (standalone service)

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| WS | `/ws` | WebSocket endpoint for real-time execution updates |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `REDIS_URL` | No | Redis connection string (default: `redis://localhost:6379`) |

## Running Locally

```bash
cd services/dashboard-api
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

## Testing

```bash
pytest tests/ -v
```
