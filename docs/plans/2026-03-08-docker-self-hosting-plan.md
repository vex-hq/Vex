# Docker Self-Hosting Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** A single `docker compose up` that runs the entire Vex stack, with images published to Docker Hub under `vexhq/`.

**Architecture:** Root-level `docker-compose.yml` orchestrates 12 containers: 3 infrastructure (PostgreSQL with TimescaleDB+pgvector, Redis, MinIO), 2 one-shot (migrations, bucket creation), 6 application services, and 1 frontend. A migrations init container runs Alembic before app services start. GitHub Actions builds and pushes images to Docker Hub on push to main.

**Tech Stack:** Docker, Docker Compose, Alembic, Next.js standalone, GitHub Actions, Docker Hub (`vexhq/`)

---

### Task 1: Root `.dockerignore`

**Files:**
- Create: `.dockerignore`

**Step 1: Create `.dockerignore`**

```
.git
.github
.venv
venv
env
__pycache__
*.pyc
node_modules
.next
.turbo
*.egg-info
dist
build
.eggs
.coverage
htmlcov
.pytest_cache
*.log
*.png
*.jpeg
*.jpg
*.zip
.DS_Store
.env
.env.local
.env.*.local
.terraform
*.tfstate
*.tfstate.backup
*.tfvars
supermemory/
mem0/
vex-final/
.playwright-mcp/
docs/
```

**Step 2: Verify**

Run: `wc -l .dockerignore`
Expected: File exists with entries.

**Step 3: Commit**

```bash
git add .dockerignore
git commit -m "chore: add root .dockerignore for Docker builds"
```

---

### Task 2: Migrations Dockerfile

**Files:**
- Create: `services/migrations/Dockerfile`

The migrations container waits for Postgres, runs `alembic upgrade head`, and exits.

**Step 1: Create `services/migrations/Dockerfile`**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install migration dependencies
RUN pip install --no-cache-dir alembic>=1.12.0 psycopg2-binary>=2.9.0 sqlalchemy>=2.0.0

# Copy migration files
COPY services/migrations/alembic.ini /app/alembic.ini
COPY services/migrations/alembic /app/alembic

# Override sqlalchemy.url — the entry point reads DATABASE_URL from env
CMD ["alembic", "upgrade", "head"]
```

**Step 2: Test the build**

Run: `docker build -f services/migrations/Dockerfile -t vexhq/migrations:test .`
Expected: Build succeeds.

**Step 3: Verify alembic.ini reads DATABASE_URL**

Read `services/migrations/alembic/env.py` — confirm it reads `DATABASE_URL` from env and overrides `sqlalchemy.url`. The existing `env.py` at line ~20 does:
```python
url = os.environ.get("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
```

If it doesn't, add that logic. The default in `alembic.ini` uses the standard local dev DSN.  <!-- pragma: allowlist secret -->

**Step 4: Commit**

```bash
git add services/migrations/Dockerfile
git commit -m "chore: add Dockerfile for migrations init container"
```

---

### Task 3: Dashboard Dockerfile

**Files:**
- Create: `Dashboard/Dockerfile`
- Modify: `Dashboard/apps/web/next.config.mjs` — add `output: "standalone"`

The Dashboard is a Next.js app in a Turborepo monorepo. We need standalone output for a minimal Docker image.

**Step 1: Enable standalone output in Next.js config**

In `Dashboard/apps/web/next.config.mjs`, add `output: 'standalone'` to the config object. Find the line where the config is defined and add:

```js
output: 'standalone',
```

This goes in the main config object alongside `experimental`, `images`, etc.

**Step 2: Create `Dashboard/Dockerfile`**

```dockerfile
FROM node:20-alpine AS base

# Install pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate

FROM base AS deps
WORKDIR /app

# Copy workspace config
COPY Dashboard/package.json Dashboard/pnpm-lock.yaml Dashboard/pnpm-workspace.yaml Dashboard/turbo.json ./
COPY Dashboard/apps/web/package.json ./apps/web/package.json

# Copy internal package manifests
COPY Dashboard/packages/ ./packages/

# Install dependencies
RUN pnpm install --frozen-lockfile

FROM base AS builder
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/apps/web/node_modules ./apps/web/node_modules
COPY --from=deps /app/packages ./packages
COPY Dashboard/ ./

# Set build-time env vars for self-hosting defaults
ENV NEXT_PUBLIC_SITE_URL=http://localhost:3000
ENV NEXT_PUBLIC_PRODUCT_NAME=Vex
ENV NEXT_PUBLIC_SITE_TITLE="Vex - Runtime Reliability for AI Agents"
ENV NEXT_PUBLIC_DEFAULT_THEME_MODE=light
ENV NEXT_PUBLIC_ENABLE_THEME_TOGGLE=true
ENV NEXT_PUBLIC_ENABLE_TEAM_ACCOUNTS=true
ENV NEXT_PUBLIC_ENABLE_TEAM_ACCOUNTS_CREATION=true
ENV NEXT_PUBLIC_AUTH_PASSWORD=true
ENV NEXT_TELEMETRY_DISABLED=1

RUN pnpm --filter web build

FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000

# Copy standalone output
COPY --from=builder /app/apps/web/.next/standalone ./
COPY --from=builder /app/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder /app/apps/web/public ./apps/web/public

EXPOSE 3000

CMD ["node", "apps/web/server.js"]
```

**Important notes:**
- The standalone build path may differ based on turborepo structure. After building locally, check if the standalone output is at `apps/web/.next/standalone` or `.next/standalone`.
- The `COPY Dashboard/` in the builder stage copies from the build context (repo root). The Dockerfile path in compose is `Dashboard/Dockerfile` but context is `.` (repo root).
- Internal `@kit/*` packages need their `package.json` files copied in the deps stage. The `COPY Dashboard/packages/ ./packages/` handles this.

**Step 3: Test the build**

Run: `docker build -f Dashboard/Dockerfile -t vexhq/dashboard:test .`
Expected: Build succeeds (may take a few minutes for Next.js build).

**Step 4: Commit**

```bash
git add Dashboard/Dockerfile Dashboard/apps/web/next.config.mjs
git commit -m "feat: add Dashboard Dockerfile with Next.js standalone output"
```

---

### Task 4: Root `.env.example`

**Files:**
- Create: `.env.example`

**Step 1: Create `.env.example`**

```env
# ============================================================
# Vex Self-Hosted Configuration
# ============================================================
# Copy this file to .env and fill in the required values.
# Only LLM provider keys are required — everything else has defaults.

# ------------------------------------------------------------
# LLM Provider (REQUIRED — pick at least one)
# ------------------------------------------------------------
# Option A: LiteLLM Proxy (recommended if you have one)
LITELLM_API_URL=
LITELLM_API_KEY=

# Option B: Direct provider keys
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

# Option C: OpenRouter
OPENROUTER_API_KEY=

# ------------------------------------------------------------
# Embedding Provider (REQUIRED for session memory)
# ------------------------------------------------------------
TOGETHER_API_KEY=

# ------------------------------------------------------------
# Verification Settings (optional)
# ------------------------------------------------------------
# VERIFICATION_MODEL=openai/gpt-4o-mini
# VERIFICATION_TIMEOUT_S=30
# MEMORY_ENABLED=true
# MEMORY_EMBEDDING_MODEL=intfloat/multilingual-e5-large-instruct

# ------------------------------------------------------------
# Infrastructure (defaults work out of the box)
# ------------------------------------------------------------
POSTGRES_PASSWORD=agentguard_dev
# MINIO_ROOT_USER=agentguard
# MINIO_ROOT_PASSWORD=agentguard_dev

# ------------------------------------------------------------
# Dashboard (optional)
# ------------------------------------------------------------
# NEXT_PUBLIC_SITE_URL=http://localhost:3000
# SUPABASE_SECRET_KEY=
# NEXT_PUBLIC_SUPABASE_URL=
# NEXT_PUBLIC_SUPABASE_PUBLIC_KEY=
```

**Step 2: Commit**

```bash
git add .env.example
git commit -m "chore: add .env.example for self-hosted configuration"
```

---

### Task 5: Root `docker-compose.yml`

**Files:**
- Create: `docker-compose.yml`

This is the main deliverable. All 12 containers with proper dependency ordering.

**Step 1: Create `docker-compose.yml`**

```yaml
# Vex — Self-Hosted Docker Compose
# Usage:
#   cp .env.example .env   # edit with your LLM keys
#   docker compose up

services:
  # ── Infrastructure ─────────────────────────────────────────

  postgres:
    image: timescale/timescaledb-ha:pg16
    environment:
      POSTGRES_DB: agentguard
      POSTGRES_USER: agentguard
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-agentguard_dev}
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/home/postgres/pgdata/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U agentguard"]
      interval: 5s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    ports:
      - "6379:6379"
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 10

  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER:-agentguard}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD:-agentguard_dev}
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - miniodata:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 5s
      timeout: 5s
      retries: 10

  createbuckets:
    image: minio/mc
    depends_on:
      minio:
        condition: service_healthy
    entrypoint: >
      /bin/sh -c "
      mc alias set local http://minio:9000 $${MINIO_ROOT_USER:-agentguard} $${MINIO_ROOT_PASSWORD:-agentguard_dev};
      mc mb local/agentguard-traces --ignore-existing;
      exit 0;
      "

  # ── Migrations (init container) ────────────────────────────

  migrations:
    image: vexhq/migrations:latest
    build:
      context: .
      dockerfile: services/migrations/Dockerfile
    environment:
      DATABASE_URL: postgresql://agentguard:${POSTGRES_PASSWORD:-agentguard_dev}@postgres:5432/agentguard
    depends_on:
      postgres:
        condition: service_healthy

  # ── Application Services ───────────────────────────────────

  sync-gateway:
    image: vexhq/sync-gateway:latest
    build:
      context: .
      dockerfile: services/sync-gateway/Dockerfile
    ports:
      - "8080:8000"
    environment:
      REDIS_URL: redis://redis:6379
      DATABASE_URL: postgresql://agentguard:${POSTGRES_PASSWORD:-agentguard_dev}@postgres:5432/agentguard
      LITELLM_API_URL: ${LITELLM_API_URL:-}
      LITELLM_API_KEY: ${LITELLM_API_KEY:-}
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
      OPENROUTER_API_KEY: ${OPENROUTER_API_KEY:-}
      TOGETHER_API_KEY: ${TOGETHER_API_KEY:-}
      VERIFICATION_MODEL: ${VERIFICATION_MODEL:-}
      VERIFICATION_TIMEOUT_S: ${VERIFICATION_TIMEOUT_S:-30}
      MEMORY_ENABLED: ${MEMORY_ENABLED:-true}
      MEMORY_EMBEDDING_MODEL: ${MEMORY_EMBEDDING_MODEL:-intfloat/multilingual-e5-large-instruct}
      GATEWAY_TIMEOUT_S: ${GATEWAY_TIMEOUT_S:-2.0}
      CORRECTION_TIMEOUT_S: ${CORRECTION_TIMEOUT_S:-10.0}
    depends_on:
      migrations:
        condition: service_completed_successfully
      redis:
        condition: service_healthy

  ingestion-api:
    image: vexhq/ingestion-api:latest
    build:
      context: .
      dockerfile: services/ingestion-api/Dockerfile
    ports:
      - "8081:8000"
    environment:
      REDIS_URL: redis://redis:6379
      DATABASE_URL: postgresql://agentguard:${POSTGRES_PASSWORD:-agentguard_dev}@postgres:5432/agentguard
    depends_on:
      migrations:
        condition: service_completed_successfully
      redis:
        condition: service_healthy

  async-worker:
    image: vexhq/async-worker:latest
    build:
      context: .
      dockerfile: services/async-worker/Dockerfile
    environment:
      REDIS_URL: redis://redis:6379
      DATABASE_URL: postgresql://agentguard:${POSTGRES_PASSWORD:-agentguard_dev}@postgres:5432/agentguard
      LITELLM_API_URL: ${LITELLM_API_URL:-}
      LITELLM_API_KEY: ${LITELLM_API_KEY:-}
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
      OPENROUTER_API_KEY: ${OPENROUTER_API_KEY:-}
      TOGETHER_API_KEY: ${TOGETHER_API_KEY:-}
      VERIFICATION_MODEL: ${VERIFICATION_MODEL:-}
      VERIFICATION_TIMEOUT_S: ${VERIFICATION_TIMEOUT_S:-30}
      MEMORY_ENABLED: ${MEMORY_ENABLED:-true}
      MEMORY_EMBEDDING_MODEL: ${MEMORY_EMBEDDING_MODEL:-intfloat/multilingual-e5-large-instruct}
      CONSUMER_NAME: async-worker-1
    depends_on:
      migrations:
        condition: service_completed_successfully
      redis:
        condition: service_healthy

  storage-worker:
    image: vexhq/storage-worker:latest
    build:
      context: .
      dockerfile: services/storage-worker/Dockerfile
    environment:
      REDIS_URL: redis://redis:6379
      DATABASE_URL: postgresql://agentguard:${POSTGRES_PASSWORD:-agentguard_dev}@postgres:5432/agentguard
      S3_ENDPOINT: http://minio:9000
      S3_ACCESS_KEY: ${MINIO_ROOT_USER:-agentguard}
      S3_SECRET_KEY: ${MINIO_ROOT_PASSWORD:-agentguard_dev}
      S3_BUCKET: agentguard-traces
      CONSUMER_NAME: storage-worker-1
    depends_on:
      migrations:
        condition: service_completed_successfully
      redis:
        condition: service_healthy
      createbuckets:
        condition: service_completed_successfully

  alert-service:
    image: vexhq/alert-service:latest
    build:
      context: .
      dockerfile: services/alert-service/Dockerfile
    environment:
      REDIS_URL: redis://redis:6379
      DATABASE_URL: postgresql://agentguard:${POSTGRES_PASSWORD:-agentguard_dev}@postgres:5432/agentguard
      CONSUMER_NAME: alert-worker-1
    depends_on:
      migrations:
        condition: service_completed_successfully
      redis:
        condition: service_healthy

  dashboard-api:
    image: vexhq/dashboard-api:latest
    build:
      context: .
      dockerfile: services/dashboard-api/Dockerfile
    ports:
      - "8082:8001"
    environment:
      REDIS_URL: redis://redis:6379
    depends_on:
      redis:
        condition: service_healthy

  # ── Frontend ───────────────────────────────────────────────

  dashboard:
    image: vexhq/dashboard:latest
    build:
      context: .
      dockerfile: Dashboard/Dockerfile
    ports:
      - "3000:3000"
    environment:
      NEXT_PUBLIC_SITE_URL: ${NEXT_PUBLIC_SITE_URL:-http://localhost:3000}
      NEXT_PUBLIC_AGENTGUARD_WS_URL: ${NEXT_PUBLIC_AGENTGUARD_WS_URL:-ws://localhost:8082/ws}
      AGENTGUARD_DATABASE_URL: postgresql://agentguard:${POSTGRES_PASSWORD:-agentguard_dev}@postgres:5432/agentguard
      AGENTGUARD_S3_ENDPOINT: http://minio:9000
      AGENTGUARD_S3_ACCESS_KEY: ${MINIO_ROOT_USER:-agentguard}
      AGENTGUARD_S3_SECRET_KEY: ${MINIO_ROOT_PASSWORD:-agentguard_dev}
      AGENTGUARD_S3_BUCKET: agentguard-traces
    depends_on:
      migrations:
        condition: service_completed_successfully

volumes:
  pgdata:
  redisdata:
  miniodata:
```

**Step 2: Test the compose (build only, no run)**

Run: `docker compose config`
Expected: Valid YAML output, no errors.

Run: `docker compose build`
Expected: All images build successfully. Dashboard build will take longest.

**Step 3: Test full startup**

Create a temporary `.env`:
```bash
cp .env.example .env
# Add at least one LLM key to .env
```

Run: `docker compose up`
Expected:
- Postgres starts and becomes healthy
- Redis starts and becomes healthy
- MinIO starts, createbuckets runs
- Migrations run and exit with code 0
- All 6 app services start
- Dashboard starts on port 3000
- `curl http://localhost:8080/health` returns `{"status":"healthy"}`

**Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add root docker-compose.yml for self-hosted deployment"
```

---

### Task 6: GitHub Actions — Docker Hub Publishing

**Files:**
- Create: `.github/workflows/docker-publish.yml`

This workflow builds all 8 images and pushes to Docker Hub on push to `main`.

**Prerequisites:** Set `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` as GitHub Actions secrets in the repository settings.

**Step 1: Create `.github/workflows/docker-publish.yml`**

```yaml
name: Docker Publish

on:
  push:
    branches: [main]

env:
  REGISTRY: docker.io
  NAMESPACE: vexhq

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    strategy:
      matrix:
        include:
          - service: sync-gateway
            dockerfile: services/sync-gateway/Dockerfile
          - service: ingestion-api
            dockerfile: services/ingestion-api/Dockerfile
          - service: async-worker
            dockerfile: services/async-worker/Dockerfile
          - service: storage-worker
            dockerfile: services/storage-worker/Dockerfile
          - service: alert-service
            dockerfile: services/alert-service/Dockerfile
          - service: dashboard-api
            dockerfile: services/dashboard-api/Dockerfile
          - service: migrations
            dockerfile: services/migrations/Dockerfile

    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          submodules: recursive

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}

      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.NAMESPACE }}/${{ matrix.service }}
          tags: |
            type=sha,prefix=
            type=raw,value=latest

      - name: Build and push
        uses: docker/build-push-action@v6
        with:
          context: .
          file: ${{ matrix.dockerfile }}
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

  build-and-push-dashboard:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          submodules: recursive

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}

      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.NAMESPACE }}/dashboard
          tags: |
            type=sha,prefix=
            type=raw,value=latest

      - name: Build and push Dashboard
        uses: docker/build-push-action@v6
        with:
          context: .
          file: Dashboard/Dockerfile
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

**Step 2: Commit**

```bash
git add .github/workflows/docker-publish.yml
git commit -m "ci: add Docker Hub publish workflow for all services"
```

---

### Task 7: Verify Full Stack

**No files to create — integration verification.**

**Step 1: Clean build and run**

```bash
docker compose down -v  # clean slate
cp .env.example .env
# Add LLM keys to .env
docker compose up --build
```

**Step 2: Verify all containers are running**

Run: `docker compose ps`
Expected: All services `running` except migrations and createbuckets which should show `exited (0)`.

**Step 3: Health checks**

```bash
curl http://localhost:8080/health    # sync-gateway
curl http://localhost:8081/health    # ingestion-api
curl http://localhost:8082/health    # dashboard-api
curl http://localhost:3000           # dashboard
```

All should return 200.

**Step 4: Run the smoke test against local stack**

```bash
# Create an API key in the local database first
docker compose exec postgres psql -U agentguard -d agentguard -c "
INSERT INTO api_keys (org_id, key_hash, scopes, plan, metadata)
VALUES ('self-hosted', 'test-key-hash', ARRAY['verify','ingest'], 'pro', '{}')
ON CONFLICT DO NOTHING;
"
```

Then run the smoke test pointing at localhost:
```bash
VEX_API_KEY=<local-key> VEX_API_URL=http://localhost:8080 python3 scripts/test_live_smoke.py
```

**Step 5: Commit any fixes needed**

```bash
git add -A
git commit -m "fix: adjustments from full-stack Docker verification"
```

---

### Summary of All Files

| # | File | Action |
|---|---|---|
| 1 | `.dockerignore` | Create |
| 2 | `services/migrations/Dockerfile` | Create |
| 3 | `Dashboard/Dockerfile` | Create |
| 3 | `Dashboard/apps/web/next.config.mjs` | Modify (add `output: 'standalone'`) |
| 4 | `.env.example` | Create |
| 5 | `docker-compose.yml` | Create |
| 6 | `.github/workflows/docker-publish.yml` | Create |
| 7 | Integration verification | No files |
