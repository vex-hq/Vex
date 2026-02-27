# Due Diligence Readiness — Full Sweep

**Date:** 2026-02-28
**Context:** CTO investor due diligence via public repos (Vex, Vex-Dashboard, Python-SDK, Typescript-SDK) in 3+ weeks.

---

## Section 1: Security (Critical — Do First)

### 1a. Scrub `demo/.env` from git history
- Contains live `OPENROUTER_API_KEY` and `AGENTGUARD_API_KEY`
- Use `git filter-repo` to remove from all commits
- Replace with `demo/.env.example` containing placeholder values
- Rotate both keys after scrub

### 1b. Clean screenshot PNGs from repo root
- 70+ `.png` files and a `.zip` in repo root
- Add patterns to root `.gitignore`
- Remove from tracking with `git rm --cached`

### 1c. Add pre-commit hooks to parent repo
- Currently only Dashboard has `.pre-commit-config.yaml`
- Add to parent Vex repo: detect-secrets, detect-private-key, check-added-large-files

---

## Section 2: Documentation

### 2a. `ARCHITECTURE.md` in repo root
- High-level system diagram (services, SDKs, Dashboard, data flow)
- Service responsibility table (8 services)
- Tech stack summary (FastAPI, Next.js, Neon, Redis, R2, Railway)
- How SDKs connect to ingestion-api, verification pipeline flow
- Reference detailed designs in `docs/plans/`

### 2b. Service-level READMEs (7 services)
- ingestion-api, verification-engine, sync-gateway, async-worker, alert-service, dashboard-api, storage-worker
- Each: purpose, dependencies, endpoints, env vars, how to run locally

### 2c. `CHANGELOG.md` in all 4 repos
- Vex (parent): major milestones
- Python-SDK: v0.1.0 through v0.3.0
- Typescript-SDK: v0.1.0 through v0.1.1
- Vex-Dashboard: key feature releases

### 2d. `docs/DEPLOYMENT.md`
- Self-hosting guide: docker-compose local, Railway/Vercel cloud
- Required env vars, database setup, R2/S3 configuration
- Minimum requirements

### 2e. Fix TypeScript SDK package.json
- `repository.url` still points to `Agent-X-AI/TypeScript-SDK` — update to `Vex-AI-Dev/Typescript-SDK`

---

## Section 3: CI/CD Hardening

### 3a. Python linting + type checking in CI
- Add `ruff` linting step for all services and Python SDK
- Add `mypy` type checking step
- Add `ruff.toml` config to repo root
- Add `[tool.mypy]` to service `pyproject.toml` files

### 3b. Dependency scanning
- Add `dependabot.yml` for all 4 repos (pip + npm)
- Add CodeQL workflow for SAST (Python + JavaScript/TypeScript)

### 3c. TypeScript SDK publishing workflow
- Add `.github/workflows/publish-sdk.yml` for npm

### 3d. Coverage reports
- Add `pytest-cov` with coverage threshold to Python CI
- Add coverage badge to root README
- Add vitest coverage for TypeScript SDK

---

## Section 4: Test Coverage

### 4a. Service unit tests (5 services missing tests)
- ingestion-api: request validation, event parsing, auth
- sync-gateway: sync request routing, timeout handling
- async-worker: batch processing, queue consumption
- dashboard-api: API endpoints, auth, data queries
- storage-worker: R2 uploads, Neon writes

### 4b. Expand existing service tests
- verification-engine and alert-service: review and fill gaps

### 4c. Integration test cleanup
- Verify `tests/integration/` still passes with current codebase

---

## Section 5: Repo Presentation & Git Hygiene

### 5a. README badges
- CI status, license, Python version, npm version, coverage

### 5b. SDK version alignment
- Python 0.3.0, TypeScript 0.1.1 — align or document divergence

### 5c. API documentation
- OpenAPI/Swagger auto-generation for FastAPI services
- Link from service READMEs and ARCHITECTURE.md

### 5d. Root `.gitignore` cleanup
- Add patterns for screenshots, zips, dev artifacts
