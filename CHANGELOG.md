# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Architecture documentation and service READMEs
- Pre-commit hooks with secret detection
- Dependabot and CodeQL security scanning
- Ruff linting and coverage reporting in CI

## [0.3.0] - 2026-02-24

### Changed
- Rebrand from AgentGuard to Vex across all services and SDKs
- Update all API URLs to api.tryvex.dev
- Update copyright to Vex AI, Inc.

## [0.2.0] - 2026-02-10

### Added
- Verification engine: 6-check pipeline (schema, hallucination, drift, coherence, guardrails, tool loop)
- Three-layer correction cascade (repair, constrained regeneration, full re-prompt)
- Custom guardrails (regex, keyword, threshold, LLM-based)
- Tool call tracking and loop detection
- Hourly and daily agent stats aggregation
- Alert service with webhook delivery and Slack integration

## [0.1.0] - 2026-01-20

### Added
- Initial release
- Ingestion API and sync gateway for SDK event processing
- Async worker for background verification
- Storage worker for PostgreSQL and S3 persistence
- Dashboard API with WebSocket real-time updates
- PostgreSQL schema with Alembic migrations
- Docker Compose for local development
- Integration test suite
