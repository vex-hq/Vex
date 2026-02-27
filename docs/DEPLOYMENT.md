# Vex Deployment Guide

This guide covers local development setup, environment configuration, and cloud deployment for self-hosting Vex.

## 1. Prerequisites

| Dependency | Minimum Version | Notes |
|---|---|---|
| Python | 3.9+ | Services use Python 3.11 in Docker images |
| Node.js | 20+ | Required for the Dashboard (Next.js) |
| pnpm | 8+ | Dashboard package manager |
| Docker | 24+ | For local infrastructure |
| Docker Compose | 2.0+ | V2 compose syntax |
| PostgreSQL | 16+ | TimescaleDB extension used in Docker; plain Postgres works too |
| Redis | 7+ | Used for streams, pub/sub, and caching |
| S3-compatible storage | — | MinIO (local), Cloudflare R2, or AWS S3 |

## 2. Local Development

### 2.1 Clone the repository

```bash
git clone --recurse-submodules https://github.com/Vex-AI-Dev/AgentGuard.git
cd AgentGuard
```

If you already cloned without submodules:

```bash
git submodule update --init --recursive
```

### 2.2 Start infrastructure

```bash
docker compose -f infra/docker/docker-compose.yml up -d
```

This starts three services:

- **PostgreSQL** (TimescaleDB) on port `5432`
- **Redis** on port `6379`
- **MinIO** (S3-compatible storage) on ports `9000` (API) and `9001` (console)

A sidecar container (`createbuckets`) automatically creates the `agentguard-traces` bucket in MinIO.

### 2.3 Run database migrations

```bash
cd services/migrations
pip install -r requirements.txt  # or: pip install alembic psycopg2-binary sqlalchemy
alembic upgrade head
```

### 2.4 Start backend services

Each service is a standalone Python application. From the repository root:

| Service | Command | Default Port | Description |
|---|---|---|---|
| **ingestion-api** | `cd services/ingestion-api && uvicorn app.main:app --port 8000` | 8000 | Receives traces from SDKs |
| **sync-gateway** | `cd services/sync-gateway && uvicorn app.main:app --port 8000` | 8000 | Synchronous guardrail proxy |
| **dashboard-api** | `cd services/dashboard-api && uvicorn app.main:app --port 8001` | 8001 | WebSocket API for the Dashboard |
| **async-worker** | `cd services/async-worker && python -m app.main` | — | Redis Streams consumer for async verification |
| **storage-worker** | `cd services/storage-worker && python -m app.main` | — | Redis Streams consumer; persists traces to S3 and PostgreSQL |
| **alert-service** | `cd services/alert-service && python -m app.main` | — | Redis Streams consumer; sends Slack/webhook alerts |

For local development, install each service's dependencies first:

```bash
cd services/<service-name>
pip install -e ".[dev]"
```

The `sync-gateway` and `async-worker` also depend on the shared models and verification engine packages. Set `PYTHONPATH` accordingly:

```bash
export PYTHONPATH="services/shared:services/verification-engine"
```

### 2.5 Start the Dashboard

```bash
cd Dashboard
pnpm install
pnpm dev
```

The Dashboard is a Next.js application and runs on `http://localhost:3000` by default.

## 3. Environment Variables

### Database

| Variable | Used By | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | ingestion-api, sync-gateway, storage-worker, alert-service, migrations | See `infra/.env.example` | Primary PostgreSQL connection string |
| `SUPABASE_DATABASE_URL` | ingestion-api, sync-gateway | — | Optional Supabase pooler URL; used for auth queries when set |
| `POSTGRES_PASSWORD` | docker-compose | `agentguard_dev` | Password for the local PostgreSQL container |

### Redis

| Variable | Used By | Default | Description |
|---|---|---|---|
| `REDIS_URL` | ingestion-api, sync-gateway, dashboard-api, async-worker, storage-worker, alert-service | `redis://localhost:6379` | Redis connection URL |
| `CONSUMER_NAME` | async-worker, storage-worker, alert-service | `<service>-worker-1` | Unique name for Redis Streams consumer (set per-instance for horizontal scaling) |

### S3 / Object Storage

| Variable | Used By | Default | Description |
|---|---|---|---|
| `S3_ENDPOINT` | storage-worker | `http://localhost:9000` | S3-compatible endpoint URL |
| `S3_ACCESS_KEY` | storage-worker | `agentguard` | S3 access key ID |
| `S3_SECRET_KEY` | storage-worker | `agentguard_dev` | S3 secret access key |
| `S3_BUCKET` | — (hardcoded) | `agentguard-traces` | Bucket name; currently hardcoded in `storage-worker/app/worker.py` |
| `MINIO_ROOT_USER` | docker-compose | `agentguard` | MinIO root user for local development |
| `MINIO_ROOT_PASSWORD` | docker-compose | `agentguard_dev` | MinIO root password for local development |

### LLM / Verification Engine

| Variable | Used By | Default | Description |
|---|---|---|---|
| `VERIFICATION_MODEL` | verification-engine | Model-specific default | LiteLLM model identifier for guardrail verification |
| `VERIFICATION_TIMEOUT_S` | verification-engine | Service default | Timeout in seconds for verification LLM calls |
| `CORRECTION_REPAIR_MODEL` | verification-engine | Model-specific default | LiteLLM model for output correction (repair pass) |
| `CORRECTION_STRONG_MODEL` | verification-engine | Model-specific default | LiteLLM model for output correction (strong pass) |
| `LITELLM_API_URL` | verification-engine | — | Base URL for LiteLLM-compatible API |
| `LITELLM_API_KEY` | verification-engine | — | API key for LiteLLM |
| `OPENAI_API_BASE` | verification-engine | — | Fallback: OpenAI-compatible base URL |
| `OPENAI_API_KEY` | verification-engine | — | Fallback: OpenAI API key |

### Sync Gateway

| Variable | Used By | Default | Description |
|---|---|---|---|
| `GATEWAY_TIMEOUT_S` | sync-gateway | `2.0` | Timeout for the synchronous guardrail check |
| `CORRECTION_TIMEOUT_S` | sync-gateway | `10.0` | Timeout for correction/repair operations |

### Alerts

| Variable | Used By | Default | Description |
|---|---|---|---|
| `SLACK_WEBHOOK_URL` | alert-service | — | Default Slack incoming webhook URL for all projects |
| `SLACK_WEBHOOK_URL_<PROJECT>` | alert-service | — | Per-project Slack webhook override (e.g., `SLACK_WEBHOOK_URL_MY_BOT`) |
| `WEBHOOK_URL` | alert-service | — | Generic webhook URL for alert delivery |
| `DASHBOARD_BASE_URL` | alert-service | — | Base URL of the Dashboard; used to generate links in alert messages |

## 4. Database Setup

### Alembic migrations

Migrations live in `services/migrations/alembic/versions/`. The Alembic configuration is in `services/migrations/alembic.ini`, and `services/migrations/alembic/env.py` reads the `DATABASE_URL` environment variable to override the default connection string.

**Run all pending migrations:**

```bash
cd services/migrations
DATABASE_URL="$YOUR_DATABASE_URL" alembic upgrade head
```

**Create a new migration:**

```bash
cd services/migrations
alembic revision --autogenerate -m "add_new_table"
```

**Check current migration state:**

```bash
cd services/migrations
alembic current
```

**Downgrade one revision:**

```bash
cd services/migrations
alembic downgrade -1
```

## 5. Cloud Deployment

### 5.1 Backend Services

Each service has its own `Dockerfile` in `services/<name>/Dockerfile`. All Dockerfiles are built from the repository root context:

```bash
docker build -f services/ingestion-api/Dockerfile -t vex-ingestion-api .
docker build -f services/sync-gateway/Dockerfile -t vex-sync-gateway .
docker build -f services/dashboard-api/Dockerfile -t vex-dashboard-api .
docker build -f services/async-worker/Dockerfile -t vex-async-worker .
docker build -f services/storage-worker/Dockerfile -t vex-storage-worker .
docker build -f services/alert-service/Dockerfile -t vex-alert-service .
```

Deploy to any container platform:

- **Railway** -- push the repo and configure each service as a separate Railway service, pointing to the appropriate Dockerfile.
- **AWS ECS / Fargate** -- push images to ECR and create task definitions for each service.
- **Fly.io / Render** -- create separate apps per service with the corresponding Dockerfile path.

**Port mapping:**

| Service | Exposed Port | Protocol |
|---|---|---|
| ingestion-api | 8000 | HTTP |
| sync-gateway | 8000 | HTTP |
| dashboard-api | 8001 | HTTP + WebSocket |
| async-worker | — | Background worker (no port) |
| storage-worker | — | Background worker (no port) |
| alert-service | — | Background worker (no port) |

### 5.2 Dashboard

The Dashboard is a Next.js application. Deploy to:

- **Vercel** -- connect the `Dashboard` submodule repository and deploy. Set the root directory to the repo root.
- **Any Next.js host** -- build with `pnpm build` and run with `pnpm start`.

### 5.3 Database

Options:

- **Neon** -- serverless PostgreSQL. Use the provided connection string as `DATABASE_URL`.
- **Supabase** -- provides PostgreSQL with a connection pooler. Set both `DATABASE_URL` (direct) and `SUPABASE_DATABASE_URL` (pooler) for auth queries.
- **Self-hosted PostgreSQL 16+** -- use TimescaleDB extension if you want time-series optimizations for trace data.

### 5.4 Object Storage

Options:

- **Cloudflare R2** -- S3-compatible. Set `S3_ENDPOINT` to your R2 endpoint, and `S3_ACCESS_KEY` / `S3_SECRET_KEY` to your R2 credentials. Create a bucket named `agentguard-traces`.
- **AWS S3** -- set `S3_ENDPOINT` to `https://s3.<region>.amazonaws.com` (or omit for default), and use IAM credentials.
- **MinIO** -- self-hosted S3-compatible storage for on-premises deployments.

### 5.5 Redis

Options:

- **Upstash** -- serverless Redis with Streams support. Use the provided `REDIS_URL`.
- **Redis Cloud** -- managed Redis. Ensure Streams are enabled.
- **Self-hosted Redis 7+** -- run with `--appendonly yes` for durability.

Redis Streams are used for inter-service communication. Ensure your provider supports the Streams data type.

## 6. Production Checklist

- [ ] All environment variables from Section 3 are set for each service
- [ ] Database migrations are up to date (`alembic upgrade head`)
- [ ] Redis is reachable from all services; Streams consumer groups are created automatically on first run
- [ ] S3 bucket `agentguard-traces` exists and is accessible with the configured credentials
- [ ] SSL/TLS is enabled on all public-facing endpoints (ingestion-api, sync-gateway, dashboard-api, Dashboard)
- [ ] `CONSUMER_NAME` is unique per instance when running multiple replicas of async-worker, storage-worker, or alert-service
- [ ] Health checks are configured on your container platform:
  - PostgreSQL: `pg_isready -U <user>`
  - Redis: `redis-cli ping`
  - MinIO: `curl -f http://<host>:9000/minio/health/live`
  - HTTP services: `GET /` or a dedicated `/health` endpoint
- [ ] `DASHBOARD_BASE_URL` is set for the alert-service so alert messages contain valid links
- [ ] LLM provider credentials (`LITELLM_API_KEY` or `OPENAI_API_KEY`) are configured for the verification engine
- [ ] Slack webhook URLs are configured if you want alert notifications
- [ ] Logging and monitoring are set up for all services (stdout logs are structured for container platforms)
- [ ] Backups are configured for PostgreSQL and S3 storage
