# Due Diligence Readiness — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prepare all 4 public repos (Vex, Vex-Dashboard, Python-SDK, Typescript-SDK) for CTO investor due diligence review.

**Architecture:** Five work streams executed sequentially: Security fixes first (blocking), then Documentation, CI/CD hardening, Test coverage, and Repo presentation. Each stream contains independent tasks that can be parallelized.

**Tech Stack:** git filter-repo, pre-commit, detect-secrets, ruff, mypy, pytest, pytest-cov, vitest, GitHub Actions, Dependabot, CodeQL

---

## Stream 1: Security (Critical — Do First)

### Task 1: Scrub `demo/.env` from git history

**Files:**
- Remove from history: `demo/.env`
- Keep as-is: `demo/.env.example` (already exists with placeholders)

**Step 1: Verify the secret exposure**

```bash
cat demo/.env
# Expected: Contains real OPENROUTER_API_KEY and AGENTGUARD_API_KEY
```

**Step 2: Remove demo/.env from git tracking**

```bash
git rm --cached demo/.env
echo "demo/.env" >> .gitignore  # Not needed — root .gitignore already has .env
```

Actually, root `.gitignore` already has `.env` which should match `demo/.env`. Check why it's tracked:

```bash
git ls-files demo/.env
# If tracked, it was added before .gitignore rule
git rm --cached demo/.env
```

**Step 3: Scrub from entire git history**

```bash
pip3 install git-filter-repo --break-system-packages
git filter-repo --invert-paths --path demo/.env --force
```

**Step 4: Re-add remote and force push**

```bash
git remote add origin https://github.com/Vex-AI-Dev/Vex.git
git push origin main --force
```

**Step 5: Rotate exposed keys**

- Rotate `OPENROUTER_API_KEY` at openrouter.ai dashboard
- Rotate `AGENTGUARD_API_KEY` — generate new API key in Vex dashboard
- Update `demo/.env` locally (not tracked) with new values

**Step 6: Commit**

```bash
git add .gitignore
git commit -m "security: remove demo/.env from tracking, scrub from history"
```

---

### Task 2: Clean screenshot PNGs from repo root

**Files:**
- Modify: `.gitignore`
- Remove from tracking: all `*.png`, `*.zip` in repo root

**Step 1: Add exclusion patterns to `.gitignore`**

Append to `/Users/thakurg/Hive/Research/AgentGuard/.gitignore`:

```
# Dev artifacts / screenshots
*.png
*.zip
!**/public/**/*.png
!**/assets/**/*.png
```

**Step 2: Remove all PNGs and ZIPs from root tracking**

```bash
git rm --cached *.png 2>/dev/null
git rm --cached *.zip 2>/dev/null
```

Note: These are currently untracked (shown as `??` in git status), so `git rm --cached` may not be needed. Verify first:

```bash
git ls-files '*.png' '*.zip'
# If empty, they're already untracked — just add .gitignore patterns
```

**Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: add .gitignore patterns for dev screenshots and archives"
```

---

### Task 3: Add pre-commit hooks to parent repo

**Files:**
- Create: `.pre-commit-config.yaml`
- Create: `.secrets.baseline`

**Step 1: Create `.pre-commit-config.yaml`**

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: detect-private-key
      - id: check-added-large-files
        args: ['--maxkb=500']
      - id: check-merge-conflict
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.5.0
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline']
        exclude: '\.env\.example$|pnpm-lock\.yaml'
```

**Step 2: Install hooks and generate baseline**

```bash
pre-commit install
detect-secrets scan > .secrets.baseline
detect-secrets audit .secrets.baseline  # Mark false positives
```

**Step 3: Commit**

```bash
git add .pre-commit-config.yaml .secrets.baseline
git commit -m "security: add pre-commit hooks with secret detection"
```

---

## Stream 2: Documentation

### Task 4: Create `ARCHITECTURE.md`

**Files:**
- Create: `ARCHITECTURE.md` (repo root)

**Step 1: Write the architecture document**

Content should cover:
- **System overview** — One paragraph explaining Vex's architecture
- **Service diagram** — ASCII diagram showing: SDK → sync-gateway/ingestion-api → Redis Streams → async-worker/storage-worker/alert-service → PostgreSQL/S3
- **Service responsibility table:**

| Service | Port | Purpose | Consumes | Produces |
|---------|------|---------|----------|----------|
| sync-gateway | 8000 | Unified SDK entry point, sync verification | HTTP requests | Redis: executions.raw |
| ingestion-api | 8001 | Async event ingestion | HTTP requests | Redis: executions.raw |
| async-worker | — | Background verification | Redis: executions.raw | Redis: executions.verified |
| storage-worker | — | Persist to PostgreSQL + S3 | Redis: executions.raw, executions.verified | Redis: executions.stored |
| alert-service | — | Webhooks, Slack alerts | Redis: executions.verified | HTTP webhooks |
| dashboard-api | 8002 | WebSocket + REST for Dashboard | Redis: executions.stored | WebSocket events |
| verification-engine | — | Library: 6-check pipeline | Imported by sync-gateway, async-worker | Verification results |
| shared | — | Library: auth, models, rate limiting | Imported by all services | — |

- **Data flow** — Step-by-step from SDK call to Dashboard display
- **Tech stack** — FastAPI, Redis Streams, PostgreSQL (Neon), S3 (Cloudflare R2), Next.js (Turbo)
- **Infrastructure** — Railway (services), Vercel (Dashboard), Neon (DB), Cloudflare R2 (object storage)
- **Reference** — Link to `docs/plans/` for detailed design documents

**Step 2: Commit**

```bash
git add ARCHITECTURE.md
git commit -m "docs: add architecture overview"
```

---

### Task 5: Add READMEs to all services

**Files:**
- Create: `services/ingestion-api/README.md`
- Create: `services/sync-gateway/README.md`
- Create: `services/async-worker/README.md`
- Create: `services/storage-worker/README.md`
- Create: `services/dashboard-api/README.md`
- Create: `services/alert-service/README.md`
- Create: `services/verification-engine/README.md`
- Create: `services/shared/README.md`
- Create: `services/migrations/README.md`

**Step 1: Write each README with this template:**

```markdown
# [Service Name]

[One-line description from the module docstring]

## Responsibilities

- Bullet list of what this service does

## Dependencies

- **Redis** — streams consumed/produced
- **PostgreSQL** — tables read/written (if applicable)
- **S3** — buckets used (if applicable)
- **Internal** — shared library, verification-engine (if applicable)

## API Endpoints (if applicable)

| Method | Path | Description |
|--------|------|-------------|
| POST | /v1/verify | Synchronous verification |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| REDIS_URL | Yes | Redis connection string |

## Running Locally

\```bash
cd services/[service-name]
pip install -e ".[dev]"
python -m app.main  # or uvicorn app.main:app
\```

## Testing

\```bash
pytest tests/ -v
\```
```

Use the module docstrings already in each `app/main.py` as the description source.

**Step 2: Commit**

```bash
git add services/*/README.md services/migrations/README.md
git commit -m "docs: add READMEs to all services"
```

---

### Task 6: Create CHANGELOGs

**Files:**
- Create: `CHANGELOG.md` (Vex parent repo)
- Create in Python-SDK repo: `CHANGELOG.md`
- Create in Typescript-SDK repo: `CHANGELOG.md`
- Create in Vex-Dashboard repo: `CHANGELOG.md`

**Step 1: Write Vex parent CHANGELOG**

```markdown
# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [0.3.0] - 2026-02-24
### Changed
- Rebrand from AgentGuard to Vex across all services and SDKs
- Update all API URLs to api.tryvex.dev

## [0.2.0] - 2026-02-10
### Added
- Verification engine: 6-check pipeline (schema, hallucination, drift, coherence, guardrails, tool loop)
- Three-layer correction cascade
- Custom guardrails (regex, keyword, threshold, LLM-based)
- Tool call tracking and loop detection
- Hourly agent stats aggregation

## [0.1.0] - 2026-01-20
### Added
- Initial release
- Ingestion API, sync gateway, async worker, storage worker
- Alert service with webhook delivery and Slack integration
- Dashboard API with WebSocket real-time updates
- PostgreSQL schema with Alembic migrations
- Docker Compose for local development
```

**Step 2: Write Python-SDK CHANGELOG** (derive from GitHub releases)

```markdown
# Changelog

## [0.3.0] - 2026-02-24
### Changed
- Rebrand from AgentGuard to Vex — package renamed from `agentguard` to `vex-sdk`
- Update default API URL to api.tryvex.dev
- Update copyright to Vex AI, Inc.

## [0.2.2] - 2026-02-15
### Fixed
- Increase default timeouts for production LLM latency

## [0.2.1] - 2026-02-12
### Changed
- Update default api_url to api.tryvex.dev

## [0.2.0] - 2026-02-10
### Added
- Synchronous verification support
- Correction cascade reporting
- Conversation history tracking
- Multi-turn session management

## [0.1.0] - 2026-01-20
### Added
- Initial release of Python SDK
- Async and sync transports
- Agent registration and event ingestion
- Pydantic models for all API types
```

**Step 3: Write TypeScript-SDK CHANGELOG**

```markdown
# Changelog

## [0.1.1] - 2026-02-24
### Changed
- Rebrand from AgentGuard to Vex

## [0.1.0] - 2026-02-01
### Added
- Initial release of TypeScript SDK
- Sync and async transports
- Multi-turn session support
- Correction cascade support
- Zero runtime dependencies
```

**Step 4: Write Vex-Dashboard CHANGELOG**

```markdown
# Changelog

## [Unreleased]
### Added
- PostHog analytics integration
- Google Analytics on landing page
- Blog: "How We Detect AI Agent Drift"
- Markdown rendering in session timeline
- GitHub star widget (dark mode)
- Pre-commit hooks with detect-secrets

### Changed
- Rebrand from AgentGuard/Dashboard to Vex
- Fix licensing claims (dual-license: Apache 2.0 SDKs + AGPLv3 engine)

### Fixed
- MakerKit license check bypass for public repo
```

**Step 5: Commit each**

```bash
# In Vex parent
git add CHANGELOG.md
git commit -m "docs: add CHANGELOG"

# In each SDK/Dashboard repo (cd into submodule)
git add CHANGELOG.md
git commit -m "docs: add CHANGELOG"
git push
```

---

### Task 7: Create `docs/DEPLOYMENT.md`

**Files:**
- Create: `docs/DEPLOYMENT.md`

**Step 1: Write deployment guide**

Cover:
- **Local development** — docker-compose up (PostgreSQL, Redis, MinIO), run services
- **Cloud deployment** — Railway for services, Vercel for Dashboard, Neon for DB, Cloudflare R2 for storage
- **Required environment variables** — Complete table with descriptions
- **Database setup** — Alembic migrations: `alembic upgrade head`
- **Minimum requirements** — Python 3.9+, Node 20+, PostgreSQL 15+, Redis 7+

**Step 2: Commit**

```bash
git add docs/DEPLOYMENT.md
git commit -m "docs: add deployment guide"
```

---

### Task 8: Fix TypeScript SDK package.json repository URL

**Files:**
- Modify: `sdk/typescript/package.json`

**Step 1: Update repository URL**

Change:
```json
"repository": {
  "type": "git",
  "url": "https://github.com/Agent-X-AI/TypeScript-SDK"
}
```

To:
```json
"repository": {
  "type": "git",
  "url": "https://github.com/Vex-AI-Dev/Typescript-SDK"
}
```

**Step 2: Commit and push**

```bash
cd sdk/typescript
git add package.json
git commit -m "chore: fix repository URL to Vex-AI-Dev org"
git push
```

**Step 3: Update parent submodule ref**

```bash
cd ../..
git add sdk/typescript
git commit -m "chore: update TypeScript SDK submodule"
```

---

## Stream 3: CI/CD Hardening

### Task 9: Add ruff and mypy to Python CI

**Files:**
- Create: `ruff.toml` (repo root)
- Modify: `.github/workflows/ci.yml`
- Modify: Each service `pyproject.toml` to add mypy dev dependency

**Step 1: Create `ruff.toml`**

```toml
target-version = "py39"
line-length = 120

[lint]
select = [
    "E",    # pycodestyle errors
    "W",    # pycodestyle warnings
    "F",    # pyflakes
    "I",    # isort
    "B",    # flake8-bugbear
    "UP",   # pyupgrade
]
ignore = [
    "E501",  # line too long (handled by formatter)
]

[format]
quote-style = "double"
```

**Step 2: Add mypy to each service's dev dependencies**

In every `services/*/pyproject.toml`, add to `[project.optional-dependencies]`:

```toml
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
    "mypy>=1.8.0",
    "ruff>=0.3.0",
]
```

Also add to `sdk/python/pyproject.toml` dev deps.

**Step 3: Add lint + typecheck jobs to `.github/workflows/ci.yml`**

Add new job before existing test jobs:

```yaml
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: true
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install ruff
      - name: Lint services
        run: ruff check services/
      - name: Lint Python SDK
        run: ruff check sdk/python/
      - name: Format check
        run: ruff format --check services/ sdk/python/
```

**Step 4: Run ruff locally and fix any issues**

```bash
pip3 install ruff --break-system-packages
ruff check services/ sdk/python/ --fix
ruff format services/ sdk/python/
```

**Step 5: Commit**

```bash
git add ruff.toml .github/workflows/ci.yml services/*/pyproject.toml sdk/python/pyproject.toml
git add -u  # Any files ruff fixed
git commit -m "ci: add ruff linting and format checking to CI pipeline"
```

---

### Task 10: Add Dependabot to all repos

**Files:**
- Create: `.github/dependabot.yml` (Vex parent)
- Create: `.github/dependabot.yml` (Vex-Dashboard)
- Create: `.github/dependabot.yml` (Python-SDK)
- Create: `.github/dependabot.yml` (Typescript-SDK)

**Step 1: Create Vex parent dependabot config**

```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/services/ingestion-api"
    schedule:
      interval: "weekly"
  - package-ecosystem: "pip"
    directory: "/services/sync-gateway"
    schedule:
      interval: "weekly"
  - package-ecosystem: "pip"
    directory: "/services/async-worker"
    schedule:
      interval: "weekly"
  - package-ecosystem: "pip"
    directory: "/services/storage-worker"
    schedule:
      interval: "weekly"
  - package-ecosystem: "pip"
    directory: "/services/alert-service"
    schedule:
      interval: "weekly"
  - package-ecosystem: "pip"
    directory: "/services/dashboard-api"
    schedule:
      interval: "weekly"
  - package-ecosystem: "pip"
    directory: "/services/verification-engine"
    schedule:
      interval: "weekly"
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
```

**Step 2: Create SDK dependabot configs**

Python-SDK:
```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
```

Typescript-SDK:
```yaml
version: 2
updates:
  - package-ecosystem: "npm"
    directory: "/"
    schedule:
      interval: "weekly"
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
```

Vex-Dashboard:
```yaml
version: 2
updates:
  - package-ecosystem: "npm"
    directory: "/"
    schedule:
      interval: "weekly"
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
```

**Step 3: Commit each**

```bash
# Parent repo
git add .github/dependabot.yml
git commit -m "ci: add Dependabot for dependency scanning"

# Each submodule — cd in, add, commit, push
```

---

### Task 11: Add CodeQL SAST workflow

**Files:**
- Create: `.github/workflows/codeql.yml` (Vex parent)

**Step 1: Create CodeQL workflow**

```yaml
name: "CodeQL"

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    - cron: "0 6 * * 1"  # Monday 6am UTC

jobs:
  analyze:
    name: Analyze
    runs-on: ubuntu-latest
    permissions:
      security-events: write
    strategy:
      matrix:
        language: [python, javascript-typescript]
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: true
      - uses: github/codeql-action/init@v3
        with:
          languages: ${{ matrix.language }}
      - uses: github/codeql-action/autobuild@v3
      - uses: github/codeql-action/analyze@v3
```

**Step 2: Commit**

```bash
git add .github/workflows/codeql.yml
git commit -m "ci: add CodeQL security analysis"
```

---

### Task 12: Add TypeScript SDK npm publish workflow

**Files:**
- Create in Typescript-SDK repo: `.github/workflows/publish.yml`

**Step 1: Create publish workflow**

```yaml
name: Publish to npm

on:
  push:
    tags:
      - "v*"

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - run: npm ci
      - run: npm test
      - run: npm run typecheck

  publish:
    needs: test
    runs-on: ubuntu-latest
    permissions:
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          registry-url: "https://registry.npmjs.org"
      - run: npm ci
      - run: npm run build
      - run: npm publish --provenance --access public
        env:
          NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}
```

**Step 2: Commit and push**

```bash
cd sdk/typescript
git add .github/workflows/publish.yml
git commit -m "ci: add npm publish workflow"
git push
```

---

### Task 13: Add coverage reporting to CI

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `sdk/python/pyproject.toml`
- Modify: Root `README.md` (add coverage badge)

**Step 1: Add pytest-cov to SDK and service dev dependencies**

Already partly done in Task 9. Ensure `pytest-cov>=4.0.0` is in dev deps for sdk/python and all services.

**Step 2: Update CI SDK test job to generate coverage**

```yaml
      - name: Run SDK tests with coverage
        run: |
          cd sdk/python
          pip install -e ".[dev]"
          pytest --cov=vex_sdk --cov-report=xml --cov-report=term-missing
```

**Step 3: Add CI badge to README**

Add after existing badges in `README.md`:

```markdown
[![CI](https://github.com/Vex-AI-Dev/Vex/actions/workflows/ci.yml/badge.svg)](https://github.com/Vex-AI-Dev/Vex/actions/workflows/ci.yml)
```

**Step 4: Commit**

```bash
git add .github/workflows/ci.yml README.md sdk/python/pyproject.toml
git commit -m "ci: add coverage reporting and CI badge"
```

---

## Stream 4: Test Coverage

### Task 14: Add tests for ingestion-api

**Files:**
- Create/expand: `services/ingestion-api/tests/test_routes.py`
- Create: `services/ingestion-api/tests/test_auth.py`

**Step 1: Write route tests**

Test the FastAPI routes:
- Valid event ingestion (200)
- Missing auth header (401)
- Malformed payload (422)
- Health check endpoint

Use `httpx.AsyncClient` with FastAPI's `TestClient` pattern. Mock Redis client.

**Step 2: Write auth tests**

Test API key validation, org extraction from key.

**Step 3: Run tests**

```bash
cd services/ingestion-api
pip install -e ".[dev]"
pytest tests/ -v
```

**Step 4: Commit**

```bash
git add services/ingestion-api/tests/
git commit -m "test: add ingestion-api route and auth tests"
```

---

### Task 15: Add tests for sync-gateway

**Files:**
- Create/expand: `services/sync-gateway/tests/test_routes.py`

**Step 1: Write route tests**

Test:
- `/v1/verify` — valid sync verification request
- `/v1/ingest` — valid async ingestion request
- Auth failures
- Timeout handling
- Health check

Mock Redis and verification engine.

**Step 2: Run tests**

```bash
cd services/sync-gateway
pip install -e ".[dev]"
pytest tests/ -v
```

**Step 3: Commit**

```bash
git add services/sync-gateway/tests/
git commit -m "test: add sync-gateway route tests"
```

---

### Task 16: Add tests for async-worker

**Files:**
- Create/expand: `services/async-worker/tests/test_worker.py`

**Step 1: Write worker tests**

Test:
- Message consumption from Redis stream
- Verification pipeline invocation
- Result publishing to executions.verified
- Consumer group creation
- Error handling (malformed messages)

Mock Redis streams and verification engine.

**Step 2: Run tests**

```bash
cd services/async-worker
pip install -e ".[dev]"
pytest tests/ -v
```

**Step 3: Commit**

```bash
git add services/async-worker/tests/
git commit -m "test: add async-worker tests"
```

---

### Task 17: Add tests for dashboard-api

**Files:**
- Create/expand: `services/dashboard-api/tests/test_main.py`
- Create: `services/dashboard-api/tests/test_websocket.py`

**Step 1: Write health check test**

```python
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import create_app

@pytest.fixture
def app():
    return create_app()

@pytest.mark.asyncio
async def test_health_check(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
```

**Step 2: Write WebSocket connection test**

Test WebSocket connection, message broadcast.

**Step 3: Run tests**

```bash
cd services/dashboard-api
pip install -e ".[dev]"
pytest tests/ -v
```

**Step 4: Commit**

```bash
git add services/dashboard-api/tests/
git commit -m "test: add dashboard-api tests"
```

---

### Task 18: Add tests for storage-worker

**Files:**
- Create/expand: `services/storage-worker/tests/test_worker.py`

**Step 1: Write storage tests**

Test:
- Raw event consumption and PostgreSQL write
- S3 upload of execution data
- Verified event processing (confidence/action update)
- Error handling for DB/S3 failures

Mock Redis, PostgreSQL (SQLAlchemy), and boto3 S3 client.

**Step 2: Run tests**

```bash
cd services/storage-worker
pip install -e ".[dev]"
pytest tests/ -v
```

**Step 3: Commit**

```bash
git add services/storage-worker/tests/
git commit -m "test: add storage-worker tests"
```

---

### Task 19: Verify integration tests still pass

**Files:**
- Review: `tests/integration/test_api_key_lifecycle.py`
- Review: `tests/integration/test_sync_path.py`
- Review: `tests/integration/test_async_path.py`
- Review: `tests/integration/test_correction_path.py`

**Step 1: Read each test file to understand what infrastructure they need**

**Step 2: Run if local infra is available**

```bash
docker-compose -f infra/docker/docker-compose.yml up -d
pytest tests/integration/ -v
```

**Step 3: Document any failures and fix or skip with reason**

---

## Stream 5: Repo Presentation & Git Hygiene

### Task 20: Add README badges to all repos

**Files:**
- Modify: `README.md` (parent — add CI badge)
- Modify: `sdk/python/README.md` (add PyPI + CI badges)
- Modify: `sdk/typescript/README.md` (add npm + CI badges)

**Step 1: Add CI status badge to parent README**

Root `README.md` already has license, PyPI, npm, docs badges. Add CI badge:

```markdown
[![CI](https://github.com/Vex-AI-Dev/Vex/actions/workflows/ci.yml/badge.svg)](https://github.com/Vex-AI-Dev/Vex/actions/workflows/ci.yml)
```

**Step 2: Add badges to Python SDK README**

```markdown
[![PyPI](https://img.shields.io/pypi/v/vex-sdk)](https://pypi.org/project/vex-sdk/)
[![Python](https://img.shields.io/pypi/pyversions/vex-sdk)](https://pypi.org/project/vex-sdk/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](./LICENSE)
```

**Step 3: Add badges to TypeScript SDK README**

```markdown
[![npm](https://img.shields.io/npm/v/@vex_dev/sdk)](https://www.npmjs.com/package/@vex_dev/sdk)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](./LICENSE)
```

**Step 4: Commit each**

---

### Task 21: SDK version alignment

**Current state:** Python SDK 0.3.0, TypeScript SDK 0.1.1

**Step 1: Assess feature parity**

Read both SDKs and compare: do they support the same features? (verify, ingest, sessions, correction cascade)

**Step 2: If feature parity exists, bump TypeScript SDK to 0.3.0**

Update `package.json` version, add CHANGELOG entry, tag, and create GitHub release.

**Step 3: If not at parity, document the divergence**

Add a note to the parent README explaining version differences.

---

### Task 22: Enable OpenAPI docs for FastAPI services

**Files:**
- Verify: `services/sync-gateway/app/main.py` — FastAPI auto-generates /docs
- Verify: `services/ingestion-api/app/main.py`
- Verify: `services/dashboard-api/app/main.py`

**Step 1: Verify FastAPI apps have docs enabled (default)**

FastAPI auto-generates Swagger UI at `/docs` and OpenAPI JSON at `/openapi.json` unless explicitly disabled. Check each `create_app()` for `docs_url=None`.

**Step 2: If disabled, re-enable for development**

**Step 3: Add link to service READMEs**

```markdown
## API Documentation

Run the service locally and visit `http://localhost:PORT/docs` for interactive Swagger UI.
```

**Step 4: Commit**

---

### Task 23: Rename "agentguard" references in service pyproject.toml files

**Files:**
- Modify: All `services/*/pyproject.toml` — change `name = "agentguard-*"` to `name = "vex-*"`

**Step 1: Update all service names**

| Current | New |
|---------|-----|
| agentguard-ingestion-api | vex-ingestion-api |
| agentguard-sync-gateway | vex-sync-gateway |
| agentguard-async-worker | vex-async-worker |
| agentguard-storage-worker | vex-storage-worker |
| agentguard-alert-service | vex-alert-service |
| agentguard-dashboard-api | vex-dashboard-api |
| agentguard-verification-engine | vex-verification-engine |
| agentguard-shared | vex-shared |
| agentguard-migrations | vex-migrations |

**Step 2: Commit**

```bash
git add services/*/pyproject.toml services/migrations/pyproject.toml
git commit -m "chore: rename service packages from agentguard to vex"
```

---

### Task 24: Final review and push

**Step 1: Run full CI locally**

```bash
# Lint
ruff check services/ sdk/python/

# Tests
cd sdk/python && pytest tests/ -v && cd ../..
cd services/verification-engine && pytest tests/ -v && cd ../..
cd services/alert-service && pytest tests/ -v && cd ../..
# ... each service

# Dashboard typecheck
cd Dashboard && pnpm typecheck && cd ..
```

**Step 2: Push all repos**

```bash
# Push each submodule first
cd sdk/typescript && git push && cd ../..
cd sdk/python && git push && cd ../..
cd Dashboard && git push && cd ../..

# Push parent
git add -A
git commit -m "chore: due diligence readiness — final cleanup"
git push
```
