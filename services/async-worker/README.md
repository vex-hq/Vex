# Async Worker

Redis Stream consumer that runs the verification engine on ingested events asynchronously.

## Responsibilities

- Consumes events from the `executions.raw` stream (consumer group: `verification-workers`)
- Runs the verification pipeline on each event (schema, hallucination, drift checks)
- Publishes verified results to the `executions.verified` stream
- Skips events already verified by the sync gateway (correction cascade path)
- Gracefully handles per-message failures without crashing the consumer loop

## Dependencies

### External
- **Redis** — consumes `executions.raw`, produces to `executions.verified`

### Internal
- **shared** — `models.IngestEvent`, `redis_config`
- **verification-engine** — `pipeline.verify`

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `REDIS_URL` | No | Redis connection string (default: `redis://localhost:6379`) |
| `CONSUMER_NAME` | No | Consumer identity within the group (default: `async-worker-1`) |
| `VERIFICATION_MODEL` | No | LLM model for verification checks (default: `claude-haiku-4-5-20251001`) |
| `LITELLM_API_URL` | No | LiteLLM proxy base URL |
| `LITELLM_API_KEY` | No | LiteLLM proxy API key |

## Running Locally

```bash
cd services/async-worker
pip install -e ".[dev]"
python -m app.main
```

## Testing

```bash
pytest tests/ -v
```
