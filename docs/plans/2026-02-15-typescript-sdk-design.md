# Vex TypeScript SDK — Design Document

**Date:** 2026-02-15
**Status:** Approved
**Package:** `vex-sdk` (npm)
**Location:** `sdk/typescript/` in monorepo

## Overview

TypeScript SDK for Vex, mirroring the Python SDK's functionality with idiomatic TS patterns. Zero runtime dependencies — uses native `fetch` for HTTP. Targets Node.js 18+, Deno, and Bun.

## Architecture

```
sdk/typescript/
├── src/
│   ├── index.ts              # Public exports
│   ├── vex.ts                # Vex client (main class)
│   ├── session.ts            # Session (multi-turn conversation grouping)
│   ├── trace.ts              # TraceContext (execution tracing)
│   ├── config.ts             # VexConfig type + defaults
│   ├── models.ts             # All types (VexResult, ExecutionEvent, etc.)
│   ├── errors.ts             # VexBlockError, VexError, ConfigurationError
│   └── transport/
│       ├── async.ts          # AsyncTransport (buffer + batch flush)
│       └── sync.ts           # SyncTransport (inline verify)
├── tests/
│   ├── vex.test.ts
│   ├── session.test.ts
│   ├── models.test.ts
│   ├── config.test.ts
│   └── transport/
│       ├── async.test.ts
│       └── sync.test.ts
├── package.json
├── tsconfig.json
└── tsup.config.ts            # ESM + CJS dual build
```

## Dependencies

**Runtime:** None (native `fetch` + `AbortController`)
**Build:** `typescript`, `tsup`
**Test:** `vitest`

## Public API

### Vex Client

```typescript
import { Vex, VexConfig, VexBlockError, VexResult, Session, ConversationTurn } from 'vex-sdk';

const vex = new Vex({
  apiKey: 'ag_live_...',
  config: { mode: 'sync', correction: 'cascade' },
});

// Callback-based trace (replaces Python's context manager)
const result = await vex.trace({
  agentId: 'my-agent',
  task: 'Summarize earnings',
  input: { query: '...' },
}, async (ctx) => {
  ctx.setGroundTruth({ revenue: '$5.2B' });
  ctx.setSchema({ type: 'object', required: ['revenue'] });
  ctx.step({ type: 'llm', name: 'gpt-4', input: '...', output: '...' });
  ctx.record({ response: 'Revenue was $5.2B' });
});

// Session (multi-turn)
const session = vex.session({ agentId: 'my-agent' });
await session.trace({ task: 'Q&A' }, async (ctx) => {
  ctx.record('Paris is the capital.');
});

await vex.close();
```

### Key Differences from Python SDK

- **Callback-based trace** instead of `with` context manager
- **`async/await` everywhere** — all operations are async
- **camelCase** throughout (JS convention)
- **Milliseconds** instead of seconds for timeouts (`timeoutMs`, `flushIntervalMs`)

## Types

### Config

```typescript
interface VexConfig {
  mode?: 'async' | 'sync';
  correction?: 'none' | 'cascade';
  transparency?: 'opaque' | 'transparent';
  apiUrl?: string;
  timeoutMs?: number;              // default 10_000
  flushIntervalMs?: number;        // default 1_000
  flushBatchSize?: number;         // default 50
  conversationWindowSize?: number; // default 10
  maxBufferSize?: number;          // default 10_000
  confidenceThreshold?: ThresholdConfig;
  logEventIds?: boolean;
}

interface ThresholdConfig {
  pass?: number;   // default 0.8
  flag?: number;   // default 0.5
  block?: number;  // default 0.3
}
```

### Models

```typescript
interface VexResult {
  output: unknown;
  confidence: number | null;
  action: 'pass' | 'flag' | 'block';
  corrections: Record<string, unknown>[] | null;
  executionId: string;
  verification: Record<string, unknown> | null;
  corrected: boolean;
  originalOutput: unknown | null;
}

interface ConversationTurn {
  sequenceNumber: number;
  input: unknown;
  output: unknown;
  task?: string;
}

interface StepRecord {
  type: string;
  name: string;
  input?: unknown;
  output?: unknown;
  durationMs?: number;
  timestamp: string;
}

interface ExecutionEvent {
  executionId: string;
  sessionId?: string;
  parentExecutionId?: string;
  sequenceNumber?: number;
  agentId: string;
  task?: string;
  input: unknown;
  output: unknown;
  steps: StepRecord[];
  tokenCount?: number;
  costEstimate?: number;
  latencyMs?: number;
  timestamp: string;
  groundTruth?: unknown;
  schemaDefinition?: Record<string, unknown>;
  conversationHistory?: ConversationTurn[];
  metadata: Record<string, unknown>;
}
```

### Errors

```typescript
class VexError extends Error {}
class ConfigurationError extends VexError {}
class VexBlockError extends VexError {
  result: VexResult;
}
```

## Transport Layer

### AsyncTransport

- Buffers events in-memory, flushes in batches to `POST /v1/ingest/batch`
- `setInterval` for periodic flush (replaces Python's daemon thread)
- Auto-flush when buffer hits `flushBatchSize`
- Drop events with `console.warn` when buffer exceeds `maxBufferSize`
- 3 retries with exponential backoff (100ms, 200ms, 400ms) for 5xx/network errors
- Header: `X-Vex-Key`

### SyncTransport

- Single event to `POST /v1/verify`
- Dual timeout: default for verification, 3x for correction cascade
- 3 retries with backoff for network errors only
- HTTP 4xx/5xx: throw immediately

### Serialization

camelCase properties converted to snake_case at the transport boundary before sending to the API. Response snake_case converted back to camelCase.

## Build Output

`tsup` configured for dual format:
- **ESM** (`dist/index.mjs`)
- **CJS** (`dist/index.cjs`)
- **Types** (`dist/index.d.ts`)

`package.json` `exports` field maps both entry points.

## Test Strategy

Mirror Python test structure with Vitest:
- **config.test.ts** — defaults, custom overrides, threshold validation
- **models.test.ts** — type construction, snake_case serialization
- **vex.test.ts** — trace (async/sync), session, error handling, VexBlockError
- **session.test.ts** — sequence increment, history accumulation, window sliding
- **transport/async.test.ts** — enqueue, flush, auto-flush, retry, buffer overflow
- **transport/sync.test.ts** — verify, retry, correction timeout, error handling

HTTP mocking via `vitest.fn()` + global `fetch` mock.

**Live smoke test:** `scripts/test_live_smoke.ts` — same 6 scenarios as Python, runnable with `npx tsx scripts/test_live_smoke.ts`.
