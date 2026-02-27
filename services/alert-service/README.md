# Alert Service

Redis Stream consumer that processes verified events and delivers alert notifications via HTTP webhooks and Slack.

## Responsibilities

- Consumes events from `executions.verified` (consumer group: `alert-workers`)
- Filters for `flag` and `block` actions; skips `pass` events for alerting
- Delivers HTTP webhook notifications with exponential backoff retry (up to 3 attempts)
- Delivers Slack Block Kit notifications via incoming webhooks
- Runs Z-score anomaly detection on cost and latency (rolling 24h window, 3-sigma threshold)
- Deduplicates alerts per (agent, alert_type) with a 5-minute suppression window
- Records all alerts in the `alerts` table with delivery status
- Feature-gates delivery channels by plan (`webhook_alerts` requires pro+, `slack_alerts` requires team+)

## Dependencies

### External
- **Redis** — consumes `executions.verified` stream
- **PostgreSQL** — reads `organizations` (plan lookup), `executions` (anomaly stats); writes to `alerts`

### Internal
- **shared** — `plan_limits.get_plan_config`, `redis_config`

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `REDIS_URL` | No | Redis connection string (default: `redis://localhost:6379`) |
| `DATABASE_URL` | No | PostgreSQL connection string (default: local dev) |
| `CONSUMER_NAME` | No | Consumer identity within the group (default: `alert-worker-1`) |
| `WEBHOOK_URL` | No | Default HTTP webhook URL for alert delivery |
| `WEBHOOK_URL_{AGENT_ID}` | No | Per-agent webhook URL override (hyphens replaced by underscores, uppercased) |
| `SLACK_WEBHOOK_URL` | No | Default Slack incoming webhook URL |
| `SLACK_WEBHOOK_URL_{AGENT_ID}` | No | Per-agent Slack webhook URL override |
| `DASHBOARD_BASE_URL` | No | Base URL for "View in Dashboard" links in Slack messages |

## Running Locally

```bash
cd services/alert-service
pip install -e ".[dev]"
python -m app.main
```

## Testing

```bash
pytest tests/ -v
```
