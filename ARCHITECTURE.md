# Vex Architecture

## Overview

Vex is the reliability layer for AI agents in production. It sits between your agent and end users, verifying outputs and auto-correcting hallucinations before they reach users.

## How It Works

```
┌──────────────────┐
│   Your Agent     │
└────────┬─────────┘
         │
    SDK (Python / TypeScript)
         │
         v
┌──────────────────┐
│  api.tryvex.dev  │
│  (Vex Engine)    │
│                  │
│  Verify → Correct│
│  → Alert         │
└────────┬─────────┘
         │
         v
┌──────────────────┐
│  Verified Output │
│  → End User      │
└──────────────────┘
```

## Components

| Component | Description | Source |
|-----------|-------------|-------|
| [Python SDK](./sdk/python) | `pip install vex-sdk` — verify, ingest, and correct agent outputs | Open source (Apache 2.0) |
| [TypeScript SDK](./sdk/typescript) | `npm install @vex_dev/sdk` — same capabilities for Node.js/Edge | Open source (Apache 2.0) |
| [Dashboard](./Dashboard) | Real-time monitoring, analytics, and guardrail configuration | Open source (AGPL v3) |
| Vex Engine | Verification pipeline, correction cascade, alerting | Managed at [api.tryvex.dev](https://api.tryvex.dev) |

## Verification

The Vex Engine runs multiple checks on every agent output:

- **Hallucination detection** — compares output against ground truth
- **Drift detection** — measures divergence from assigned task
- **Coherence checks** — evaluates cross-turn consistency
- **Custom guardrails** — org-defined rules (regex, keyword, LLM-based)
- **Schema validation** — validates structured outputs

When verification fails, the optional **correction cascade** auto-fixes the output before it reaches the user.

## Infrastructure

| Component | Provider |
|-----------|----------|
| Vex Engine | Managed (api.tryvex.dev) |
| Dashboard | Vercel (app.tryvex.dev) |
| SDKs | PyPI / npm |

For enterprise self-hosting of the engine, [contact us](https://x.com/7hakurg).

## Repository Structure

```
vex/
├── Dashboard/          # Git submodule → Real-time monitoring UI (AGPL-3.0)
├── sdk/
│   ├── python/         # Git submodule → Python SDK (Apache-2.0)
│   └── typescript/     # Git submodule → TypeScript SDK (Apache-2.0)
└── docs/               # Design documents and plans
```
