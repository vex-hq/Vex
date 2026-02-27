# Migrations

Alembic-based database migration management for the Vex PostgreSQL schema (with TimescaleDB extension).

## Responsibilities

- Manages all DDL changes to the PostgreSQL database via versioned migration scripts
- Enables the TimescaleDB extension before running migrations
- Supports both online (live database) and offline (SQL script generation) modes

## Migration History

| Version | Description |
|---------|-------------|
| 001 | Initial schema (organizations, agents, executions, check_results, alerts) |
| 002 | Fix aggregate refresh |
| 003 | Add account_slug to organizations |
| 004 | Add session columns (session_id, parent_execution_id, sequence_number) |
| 005 | Phase 2 verification columns |
| 006 | Add correction column to executions |
| 007 | API key GIN index for JSONB lookups |
| 008 | Plan-based retention enforcement |
| 009 | Add hourly_agent_stats table |
| 010 | Add tool_calls table |
| 011 | Add guardrails table |
| 012 | Add check_score_hourly table |
| 013 | Add tool_usage_daily table |

## Dependencies

### External
- **PostgreSQL** — target database
- **TimescaleDB** — extension enabled automatically in online mode
- **Alembic** — migration framework
- **SQLAlchemy** — database connectivity

### Internal
- None

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | No | PostgreSQL connection string (see `infra/.env.example` for local default) |

## Running Migrations

```bash
cd services/migrations

# Apply all pending migrations
alembic upgrade head

# Generate SQL without applying (offline mode)
alembic upgrade head --sql

# Downgrade one revision
alembic downgrade -1

# Show current revision
alembic current

# Show migration history
alembic history
```

## Creating a New Migration

```bash
alembic revision -m "description_of_change"
```
