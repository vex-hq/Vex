# Storage Worker

Redis Stream consumer that persists execution data to S3 and PostgreSQL.

## Responsibilities

- Consumes raw events from `executions.raw` (consumer group: `storage-workers`)
  - Writes full execution payloads to S3 (`agentguard-traces` bucket)
  - Inserts execution metadata into the `executions` table
  - Inserts tool call records into the `tool_calls` table
  - Auto-provisions agents in the `agents` table on first event
  - Publishes stored notifications to the `executions.stored` stream
- Consumes verified events from `executions.verified` (consumer group: `storage-verified`)
  - Updates execution rows with confidence, action, and correction status
  - Inserts individual check results into the `check_results` table
  - Publishes update notifications to `executions.stored`

## Dependencies

### External
- **Redis** — consumes `executions.raw` and `executions.verified`, produces to `executions.stored`
- **PostgreSQL** — writes to `executions`, `agents`, `tool_calls`, `check_results` tables
- **S3** — writes execution trace payloads to `agentguard-traces` bucket (key format: `{org_id}/{agent_id}/{date}/{execution_id}.json`)

### Internal
- **shared** — `models.IngestEvent`, `redis_config`

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `REDIS_URL` | No | Redis connection string (default: `redis://localhost:6379`) |
| `DATABASE_URL` | No | PostgreSQL connection string (default: local dev) |
| `S3_ENDPOINT` | No | S3/MinIO endpoint URL (default: `http://localhost:9000`) |
| `S3_ACCESS_KEY` | No | S3 access key (default: `agentguard`) |
| `S3_SECRET_KEY` | No | S3 secret key (default: `agentguard_dev`) |
| `CONSUMER_NAME` | No | Consumer identity within the group (default: `storage-worker-1`) |

## Running Locally

```bash
cd services/storage-worker
pip install -e ".[dev]"
python -m app.main
```

## Testing

```bash
pytest tests/ -v
```
