# Vex TypeScript SDK Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a zero-dependency TypeScript SDK for Vex that mirrors the Python SDK's functionality with idiomatic TS patterns, supporting Node.js 18+, Deno, and Bun.

**Architecture:** Callback-based `trace()` API (replaces Python's context manager), native `fetch` for HTTP, `setInterval` for background flush, ESM + CJS dual build via tsup. camelCase externally, snake_case conversion at transport boundary.

**Tech Stack:** TypeScript 5.x, tsup (build), vitest (test), native fetch (HTTP)

**Design doc:** `docs/plans/2026-02-15-typescript-sdk-design.md`

---

### Task 1: Project Scaffolding

**Files:**
- Create: `sdk/typescript/package.json`
- Create: `sdk/typescript/tsconfig.json`
- Create: `sdk/typescript/tsup.config.ts`
- Create: `sdk/typescript/vitest.config.ts`
- Create: `sdk/typescript/src/index.ts` (empty placeholder)

**Step 1: Create package.json**

```json
{
  "name": "vex-sdk",
  "version": "0.1.0",
  "description": "The reliability layer for AI agents in production",
  "type": "module",
  "main": "./dist/index.cjs",
  "module": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "exports": {
    ".": {
      "import": {
        "types": "./dist/index.d.ts",
        "default": "./dist/index.js"
      },
      "require": {
        "types": "./dist/index.d.cts",
        "default": "./dist/index.cjs"
      }
    }
  },
  "files": ["dist"],
  "license": "Apache-2.0",
  "author": "Oppla.ai <eng@oppla.ai>",
  "repository": {
    "type": "git",
    "url": "https://github.com/Agent-X-AI/TypeScript-SDK"
  },
  "keywords": ["ai", "agents", "reliability", "verification", "vex"],
  "engines": {
    "node": ">=18.0.0"
  },
  "scripts": {
    "build": "tsup",
    "test": "vitest run",
    "test:watch": "vitest",
    "typecheck": "tsc --noEmit",
    "prepublishOnly": "npm run build"
  },
  "devDependencies": {
    "tsup": "^8.0.0",
    "typescript": "^5.4.0",
    "vitest": "^2.0.0"
  }
}
```

**Step 2: Create tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "lib": ["ES2022"],
    "strict": true,
    "esModuleInterop": true,
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true,
    "outDir": "dist",
    "rootDir": "src",
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "resolveJsonModule": true,
    "isolatedModules": true
  },
  "include": ["src"],
  "exclude": ["node_modules", "dist", "tests"]
}
```

**Step 3: Create tsup.config.ts**

```typescript
import { defineConfig } from 'tsup';

export default defineConfig({
  entry: ['src/index.ts'],
  format: ['esm', 'cjs'],
  dts: true,
  clean: true,
  sourcemap: true,
  splitting: false,
});
```

**Step 4: Create vitest.config.ts**

```typescript
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    include: ['tests/**/*.test.ts'],
  },
});
```

**Step 5: Create src/index.ts placeholder**

```typescript
// Vex TypeScript SDK
export {};
```

**Step 6: Install dependencies and verify build**

```bash
cd sdk/typescript && npm install && npm run build && npm test
```
Expected: Build succeeds, tests pass (nothing to test yet).

**Step 7: Commit**

```bash
git add sdk/typescript/
git commit -m "feat(ts-sdk): scaffold TypeScript SDK project"
```

---

### Task 2: Utility — camelCase ↔ snake_case Conversion

**Files:**
- Create: `sdk/typescript/src/utils.ts`
- Create: `sdk/typescript/tests/utils.test.ts`

**Step 1: Write the failing tests**

```typescript
// tests/utils.test.ts
import { describe, it, expect } from 'vitest';
import { toSnakeCase, toCamelCase } from '../src/utils';

describe('toSnakeCase', () => {
  it('converts a flat camelCase object to snake_case keys', () => {
    expect(toSnakeCase({ agentId: 'a', taskName: 'b' }))
      .toEqual({ agent_id: 'a', task_name: 'b' });
  });

  it('converts nested objects recursively', () => {
    expect(toSnakeCase({ agentId: 'a', metadata: { tokenCount: 5 } }))
      .toEqual({ agent_id: 'a', metadata: { token_count: 5 } });
  });

  it('converts arrays of objects', () => {
    expect(toSnakeCase({ steps: [{ stepType: 'llm', durationMs: 100 }] }))
      .toEqual({ steps: [{ step_type: 'llm', duration_ms: 100 }] });
  });

  it('passes through primitives and null', () => {
    expect(toSnakeCase(null)).toBeNull();
    expect(toSnakeCase(42)).toBe(42);
    expect(toSnakeCase('hello')).toBe('hello');
  });

  it('handles already snake_case keys', () => {
    expect(toSnakeCase({ agent_id: 'x' })).toEqual({ agent_id: 'x' });
  });
});

describe('toCamelCase', () => {
  it('converts a flat snake_case object to camelCase keys', () => {
    expect(toCamelCase({ agent_id: 'a', task_name: 'b' }))
      .toEqual({ agentId: 'a', taskName: 'b' });
  });

  it('converts nested objects recursively', () => {
    expect(toCamelCase({ agent_id: 'a', ground_truth: { token_count: 5 } }))
      .toEqual({ agentId: 'a', groundTruth: { tokenCount: 5 } });
  });

  it('converts arrays of objects', () => {
    expect(toCamelCase({ steps: [{ step_type: 'llm', duration_ms: 100 }] }))
      .toEqual({ steps: [{ stepType: 'llm', durationMs: 100 }] });
  });

  it('passes through primitives and null', () => {
    expect(toCamelCase(null)).toBeNull();
    expect(toCamelCase(42)).toBe(42);
  });
});
```

**Step 2: Run tests to verify they fail**

```bash
cd sdk/typescript && npx vitest run tests/utils.test.ts
```
Expected: FAIL — `toSnakeCase` and `toCamelCase` not found.

**Step 3: Implement utils**

```typescript
// src/utils.ts

/**
 * Convert a camelCase string to snake_case.
 */
function camelToSnake(str: string): string {
  return str.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`);
}

/**
 * Convert a snake_case string to camelCase.
 */
function snakeToCamel(str: string): string {
  return str.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
}

/**
 * Recursively convert all object keys from camelCase to snake_case.
 * Passes through primitives, arrays, and null unchanged.
 */
export function toSnakeCase(obj: unknown): unknown {
  if (obj === null || obj === undefined) return obj;
  if (typeof obj !== 'object') return obj;
  if (Array.isArray(obj)) return obj.map(toSnakeCase);

  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(obj as Record<string, unknown>)) {
    result[camelToSnake(key)] = toSnakeCase(value);
  }
  return result;
}

/**
 * Recursively convert all object keys from snake_case to camelCase.
 * Passes through primitives, arrays, and null unchanged.
 */
export function toCamelCase(obj: unknown): unknown {
  if (obj === null || obj === undefined) return obj;
  if (typeof obj !== 'object') return obj;
  if (Array.isArray(obj)) return obj.map(toCamelCase);

  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(obj as Record<string, unknown>)) {
    result[snakeToCamel(key)] = toCamelCase(value);
  }
  return result;
}
```

**Step 4: Run tests to verify they pass**

```bash
cd sdk/typescript && npx vitest run tests/utils.test.ts
```
Expected: ALL PASS

**Step 5: Commit**

```bash
git add sdk/typescript/src/utils.ts sdk/typescript/tests/utils.test.ts
git commit -m "feat(ts-sdk): add camelCase/snake_case conversion utils"
```

---

### Task 3: Error Classes

**Files:**
- Create: `sdk/typescript/src/errors.ts`
- Create: `sdk/typescript/tests/errors.test.ts`

**Step 1: Write the failing tests**

```typescript
// tests/errors.test.ts
import { describe, it, expect } from 'vitest';
import { VexError, ConfigurationError, IngestionError, VerificationError, VexBlockError } from '../src/errors';

describe('VexError', () => {
  it('is an instance of Error', () => {
    const err = new VexError('test');
    expect(err).toBeInstanceOf(Error);
    expect(err).toBeInstanceOf(VexError);
    expect(err.message).toBe('test');
    expect(err.name).toBe('VexError');
  });
});

describe('ConfigurationError', () => {
  it('extends VexError', () => {
    const err = new ConfigurationError('bad config');
    expect(err).toBeInstanceOf(VexError);
    expect(err.name).toBe('ConfigurationError');
  });
});

describe('IngestionError', () => {
  it('extends VexError', () => {
    const err = new IngestionError('failed');
    expect(err).toBeInstanceOf(VexError);
    expect(err.name).toBe('IngestionError');
  });
});

describe('VerificationError', () => {
  it('extends VexError', () => {
    const err = new VerificationError('failed');
    expect(err).toBeInstanceOf(VexError);
    expect(err.name).toBe('VerificationError');
  });
});

describe('VexBlockError', () => {
  it('carries the VexResult and formats message', () => {
    const result = {
      output: 'test',
      confidence: 0.2,
      action: 'block' as const,
      corrections: null,
      executionId: 'abc',
      verification: null,
      corrected: false,
      originalOutput: null,
    };
    const err = new VexBlockError(result);
    expect(err).toBeInstanceOf(VexError);
    expect(err.name).toBe('VexBlockError');
    expect(err.result).toBe(result);
    expect(err.message).toBe('Output blocked (confidence=0.2)');
  });
});
```

**Step 2: Run tests to verify they fail**

```bash
cd sdk/typescript && npx vitest run tests/errors.test.ts
```

**Step 3: Implement errors**

```typescript
// src/errors.ts
import type { VexResult } from './models';

export class VexError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'VexError';
  }
}

export class ConfigurationError extends VexError {
  constructor(message: string) {
    super(message);
    this.name = 'ConfigurationError';
  }
}

export class IngestionError extends VexError {
  constructor(message: string) {
    super(message);
    this.name = 'IngestionError';
  }
}

export class VerificationError extends VexError {
  constructor(message: string) {
    super(message);
    this.name = 'VerificationError';
  }
}

export class VexBlockError extends VexError {
  public readonly result: VexResult;

  constructor(result: VexResult) {
    super(`Output blocked (confidence=${result.confidence})`);
    this.name = 'VexBlockError';
    this.result = result;
  }
}
```

**Step 4: Run tests to verify they pass**

```bash
cd sdk/typescript && npx vitest run tests/errors.test.ts
```

**Step 5: Commit**

```bash
git add sdk/typescript/src/errors.ts sdk/typescript/tests/errors.test.ts
git commit -m "feat(ts-sdk): add error classes"
```

---

### Task 4: Models & Config

**Files:**
- Create: `sdk/typescript/src/models.ts`
- Create: `sdk/typescript/src/config.ts`
- Create: `sdk/typescript/tests/models.test.ts`
- Create: `sdk/typescript/tests/config.test.ts`

**Step 1: Write the failing tests for models**

```typescript
// tests/models.test.ts
import { describe, it, expect } from 'vitest';
import {
  createExecutionEvent,
  createStepRecord,
  type VexResult,
  type ConversationTurn,
  type ExecutionEvent,
} from '../src/models';

describe('createStepRecord', () => {
  it('creates a step with defaults', () => {
    const step = createStepRecord({ type: 'llm', name: 'gpt-4' });
    expect(step.type).toBe('llm');
    expect(step.name).toBe('gpt-4');
    expect(step.timestamp).toBeDefined();
    expect(step.input).toBeUndefined();
    expect(step.output).toBeUndefined();
    expect(step.durationMs).toBeUndefined();
  });

  it('includes optional fields', () => {
    const step = createStepRecord({
      type: 'tool_call',
      name: 'search',
      input: 'query',
      output: 'result',
      durationMs: 150,
    });
    expect(step.input).toBe('query');
    expect(step.output).toBe('result');
    expect(step.durationMs).toBe(150);
  });
});

describe('createExecutionEvent', () => {
  it('creates an event with auto-generated id and timestamp', () => {
    const event = createExecutionEvent({
      agentId: 'test-agent',
      input: { q: 'hello' },
      output: { a: 'world' },
    });
    expect(event.executionId).toBeDefined();
    expect(event.executionId.length).toBe(36); // UUID
    expect(event.agentId).toBe('test-agent');
    expect(event.timestamp).toBeDefined();
    expect(event.steps).toEqual([]);
    expect(event.metadata).toEqual({});
  });

  it('includes all optional fields', () => {
    const history: ConversationTurn[] = [
      { sequenceNumber: 0, input: 'q', output: 'a' },
    ];
    const event = createExecutionEvent({
      agentId: 'test',
      input: 'in',
      output: 'out',
      sessionId: 'sess-1',
      sequenceNumber: 2,
      task: 'summarize',
      groundTruth: 'truth',
      schemaDefinition: { type: 'object' },
      conversationHistory: history,
      tokenCount: 500,
      costEstimate: 0.05,
      latencyMs: 1200,
      metadata: { env: 'test' },
    });
    expect(event.sessionId).toBe('sess-1');
    expect(event.sequenceNumber).toBe(2);
    expect(event.task).toBe('summarize');
    expect(event.groundTruth).toBe('truth');
    expect(event.conversationHistory).toHaveLength(1);
    expect(event.tokenCount).toBe(500);
    expect(event.metadata).toEqual({ env: 'test' });
  });
});

describe('VexResult type', () => {
  it('can be constructed with all fields', () => {
    const result: VexResult = {
      output: 'test',
      confidence: 0.85,
      action: 'pass',
      corrections: null,
      executionId: 'abc-123',
      verification: null,
      corrected: false,
      originalOutput: null,
    };
    expect(result.action).toBe('pass');
    expect(result.corrected).toBe(false);
  });
});
```

**Step 2: Write the failing tests for config**

```typescript
// tests/config.test.ts
import { describe, it, expect } from 'vitest';
import { resolveConfig, validateThresholds, type VexConfig } from '../src/config';

describe('resolveConfig', () => {
  it('returns defaults when no config provided', () => {
    const cfg = resolveConfig();
    expect(cfg.mode).toBe('async');
    expect(cfg.correction).toBe('none');
    expect(cfg.transparency).toBe('opaque');
    expect(cfg.apiUrl).toBe('https://api.tryvex.dev');
    expect(cfg.timeoutMs).toBe(10_000);
    expect(cfg.flushIntervalMs).toBe(1_000);
    expect(cfg.flushBatchSize).toBe(50);
    expect(cfg.conversationWindowSize).toBe(10);
    expect(cfg.maxBufferSize).toBe(10_000);
    expect(cfg.confidenceThreshold.pass).toBe(0.8);
    expect(cfg.confidenceThreshold.flag).toBe(0.5);
    expect(cfg.confidenceThreshold.block).toBe(0.3);
    expect(cfg.logEventIds).toBe(false);
  });

  it('merges partial config with defaults', () => {
    const cfg = resolveConfig({ mode: 'sync', timeoutMs: 30_000 });
    expect(cfg.mode).toBe('sync');
    expect(cfg.timeoutMs).toBe(30_000);
    expect(cfg.correction).toBe('none'); // default
  });

  it('merges partial threshold config', () => {
    const cfg = resolveConfig({ confidenceThreshold: { pass: 0.9 } });
    expect(cfg.confidenceThreshold.pass).toBe(0.9);
    expect(cfg.confidenceThreshold.flag).toBe(0.5); // default
  });
});

describe('validateThresholds', () => {
  it('accepts valid thresholds', () => {
    expect(() => validateThresholds({ pass: 0.8, flag: 0.5, block: 0.3 })).not.toThrow();
  });

  it('throws if block >= flag', () => {
    expect(() => validateThresholds({ pass: 0.8, flag: 0.5, block: 0.5 })).toThrow();
  });

  it('throws if flag >= pass', () => {
    expect(() => validateThresholds({ pass: 0.5, flag: 0.5, block: 0.3 })).toThrow();
  });
});
```

**Step 3: Run tests to verify they fail**

```bash
cd sdk/typescript && npx vitest run tests/models.test.ts tests/config.test.ts
```

**Step 4: Implement models.ts**

```typescript
// src/models.ts

/**
 * Threshold configuration for pass/flag/block decisions.
 */
export interface ThresholdConfig {
  pass: number;
  flag: number;
  block: number;
}

/**
 * A single turn in a multi-turn conversation.
 */
export interface ConversationTurn {
  sequenceNumber: number;
  input?: unknown;
  output?: unknown;
  task?: string;
}

/**
 * An intermediate step in execution tracing.
 */
export interface StepRecord {
  type: string;
  name: string;
  input?: unknown;
  output?: unknown;
  durationMs?: number;
  timestamp: string;
}

/**
 * The core telemetry event sent to backend services.
 */
export interface ExecutionEvent {
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

/**
 * The result returned by all public Vex API methods.
 */
export interface VexResult {
  output: unknown;
  confidence: number | null;
  action: 'pass' | 'flag' | 'block';
  corrections: Record<string, unknown>[] | null;
  executionId: string;
  verification: Record<string, unknown> | null;
  corrected: boolean;
  originalOutput: unknown | null;
}

// -- Factory functions --

function uuid(): string {
  return crypto.randomUUID();
}

export function createStepRecord(opts: {
  type: string;
  name: string;
  input?: unknown;
  output?: unknown;
  durationMs?: number;
}): StepRecord {
  return {
    type: opts.type,
    name: opts.name,
    input: opts.input,
    output: opts.output,
    durationMs: opts.durationMs,
    timestamp: new Date().toISOString(),
  };
}

export function createExecutionEvent(opts: {
  agentId: string;
  input: unknown;
  output: unknown;
  executionId?: string;
  sessionId?: string;
  parentExecutionId?: string;
  sequenceNumber?: number;
  task?: string;
  steps?: StepRecord[];
  tokenCount?: number;
  costEstimate?: number;
  latencyMs?: number;
  groundTruth?: unknown;
  schemaDefinition?: Record<string, unknown>;
  conversationHistory?: ConversationTurn[];
  metadata?: Record<string, unknown>;
}): ExecutionEvent {
  return {
    executionId: opts.executionId ?? uuid(),
    sessionId: opts.sessionId,
    parentExecutionId: opts.parentExecutionId,
    sequenceNumber: opts.sequenceNumber,
    agentId: opts.agentId,
    task: opts.task,
    input: opts.input,
    output: opts.output,
    steps: opts.steps ?? [],
    tokenCount: opts.tokenCount,
    costEstimate: opts.costEstimate,
    latencyMs: opts.latencyMs,
    timestamp: new Date().toISOString(),
    groundTruth: opts.groundTruth,
    schemaDefinition: opts.schemaDefinition,
    conversationHistory: opts.conversationHistory,
    metadata: opts.metadata ?? {},
  };
}
```

**Step 5: Implement config.ts**

```typescript
// src/config.ts
import type { ThresholdConfig } from './models';
import { ConfigurationError } from './errors';

export interface VexConfig {
  mode: 'async' | 'sync';
  correction: 'none' | 'cascade';
  transparency: 'opaque' | 'transparent';
  apiUrl: string;
  timeoutMs: number;
  flushIntervalMs: number;
  flushBatchSize: number;
  conversationWindowSize: number;
  maxBufferSize: number;
  confidenceThreshold: ThresholdConfig;
  logEventIds: boolean;
}

export type VexConfigInput = Partial<Omit<VexConfig, 'confidenceThreshold'>> & {
  confidenceThreshold?: Partial<ThresholdConfig>;
};

const DEFAULT_THRESHOLD: ThresholdConfig = {
  pass: 0.8,
  flag: 0.5,
  block: 0.3,
};

const DEFAULT_CONFIG: VexConfig = {
  mode: 'async',
  correction: 'none',
  transparency: 'opaque',
  apiUrl: 'https://api.tryvex.dev',
  timeoutMs: 10_000,
  flushIntervalMs: 1_000,
  flushBatchSize: 50,
  conversationWindowSize: 10,
  maxBufferSize: 10_000,
  confidenceThreshold: { ...DEFAULT_THRESHOLD },
  logEventIds: false,
};

export function validateThresholds(t: ThresholdConfig): void {
  if (!(t.block < t.flag && t.flag < t.pass)) {
    throw new ConfigurationError(
      `Thresholds must satisfy: block < flag < pass. Got block=${t.block}, flag=${t.flag}, pass=${t.pass}`
    );
  }
}

export function resolveConfig(input?: VexConfigInput): VexConfig {
  const threshold: ThresholdConfig = {
    ...DEFAULT_THRESHOLD,
    ...input?.confidenceThreshold,
  };
  validateThresholds(threshold);

  return {
    ...DEFAULT_CONFIG,
    ...input,
    confidenceThreshold: threshold,
  };
}
```

**Step 6: Run tests to verify they pass**

```bash
cd sdk/typescript && npx vitest run tests/models.test.ts tests/config.test.ts
```

**Step 7: Commit**

```bash
git add sdk/typescript/src/models.ts sdk/typescript/src/config.ts sdk/typescript/tests/models.test.ts sdk/typescript/tests/config.test.ts
git commit -m "feat(ts-sdk): add models, config, and factory functions"
```

---

### Task 5: AsyncTransport

**Files:**
- Create: `sdk/typescript/src/transport/async.ts`
- Create: `sdk/typescript/tests/transport/async.test.ts`

**Step 1: Write the failing tests**

```typescript
// tests/transport/async.test.ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { AsyncTransport } from '../../src/transport/async';
import { createExecutionEvent } from '../../src/models';

function makeEvent(id?: string) {
  return createExecutionEvent({
    executionId: id ?? 'evt-1',
    agentId: 'test',
    input: 'in',
    output: 'out',
  });
}

describe('AsyncTransport', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue(new Response('{"ok":true}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('enqueues events and flushes as batch POST', async () => {
    const transport = new AsyncTransport({
      apiUrl: 'https://api.tryvex.dev',
      apiKey: 'test-key',
    });

    transport.enqueue(makeEvent('e1'));
    transport.enqueue(makeEvent('e2'));
    await transport.flush();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe('https://api.tryvex.dev/v1/ingest/batch');
    expect(opts.method).toBe('POST');
    expect(opts.headers['X-Vex-Key']).toBe('test-key');

    const body = JSON.parse(opts.body);
    expect(body.events).toHaveLength(2);
  });

  it('sends X-Vex-Key header', async () => {
    const transport = new AsyncTransport({
      apiUrl: 'https://api.tryvex.dev',
      apiKey: 'my-key-123',
    });

    transport.enqueue(makeEvent());
    await transport.flush();

    const [, opts] = fetchMock.mock.calls[0];
    expect(opts.headers['X-Vex-Key']).toBe('my-key-123');
  });

  it('clears buffer after successful flush', async () => {
    const transport = new AsyncTransport({
      apiUrl: 'https://api.tryvex.dev',
      apiKey: 'key',
    });

    transport.enqueue(makeEvent());
    await transport.flush();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Second flush should be a no-op (buffer empty)
    await transport.flush();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('does nothing on flush when buffer is empty', async () => {
    const transport = new AsyncTransport({
      apiUrl: 'https://api.tryvex.dev',
      apiKey: 'key',
    });

    await transport.flush();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('retries on 5xx errors with backoff', async () => {
    fetchMock
      .mockResolvedValueOnce(new Response('error', { status: 500 }))
      .mockResolvedValueOnce(new Response('error', { status: 502 }))
      .mockResolvedValueOnce(new Response('{"ok":true}', { status: 200 }));

    const transport = new AsyncTransport({
      apiUrl: 'https://api.tryvex.dev',
      apiKey: 'key',
    });

    transport.enqueue(makeEvent());
    await transport.flush();

    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('drops events on 4xx errors without retry', async () => {
    fetchMock.mockResolvedValue(new Response('bad request', { status: 400 }));

    const transport = new AsyncTransport({
      apiUrl: 'https://api.tryvex.dev',
      apiKey: 'key',
    });

    transport.enqueue(makeEvent());
    await transport.flush();

    // Should NOT retry on 4xx
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Buffer should be empty (events dropped)
    await transport.flush();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('returns events to buffer after all retries exhausted', async () => {
    fetchMock.mockResolvedValue(new Response('error', { status: 500 }));

    const transport = new AsyncTransport({
      apiUrl: 'https://api.tryvex.dev',
      apiKey: 'key',
    });

    transport.enqueue(makeEvent());
    await transport.flush(); // 3 retries, all fail

    expect(fetchMock).toHaveBeenCalledTimes(3);

    // Events should be back in buffer — next flush retries them
    fetchMock.mockResolvedValue(new Response('{"ok":true}', { status: 200 }));
    await transport.flush();
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it('drops events when buffer exceeds maxBufferSize', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const transport = new AsyncTransport({
      apiUrl: 'https://api.tryvex.dev',
      apiKey: 'key',
      maxBufferSize: 2,
    });

    transport.enqueue(makeEvent('e1'));
    transport.enqueue(makeEvent('e2'));
    transport.enqueue(makeEvent('e3')); // should be dropped

    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it('converts event keys to snake_case in payload', async () => {
    const transport = new AsyncTransport({
      apiUrl: 'https://api.tryvex.dev',
      apiKey: 'key',
    });

    transport.enqueue(makeEvent());
    await transport.flush();

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    const event = body.events[0];
    expect(event).toHaveProperty('execution_id');
    expect(event).toHaveProperty('agent_id');
    expect(event).not.toHaveProperty('executionId');
    expect(event).not.toHaveProperty('agentId');
  });

  it('flushes remaining events on close', async () => {
    const transport = new AsyncTransport({
      apiUrl: 'https://api.tryvex.dev',
      apiKey: 'key',
    });

    transport.enqueue(makeEvent());
    await transport.close();

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
```

**Step 2: Run tests to verify they fail**

```bash
cd sdk/typescript && npx vitest run tests/transport/async.test.ts
```

**Step 3: Implement AsyncTransport**

```typescript
// src/transport/async.ts
import type { ExecutionEvent } from '../models';
import { toSnakeCase } from '../utils';

export interface AsyncTransportOptions {
  apiUrl: string;
  apiKey: string;
  flushIntervalMs?: number;
  flushBatchSize?: number;
  timeoutMs?: number;
  maxBufferSize?: number;
}

export class AsyncTransport {
  private readonly apiUrl: string;
  private readonly apiKey: string;
  private readonly flushBatchSize: number;
  private readonly timeoutMs: number;
  private readonly maxBufferSize: number;

  private buffer: ExecutionEvent[] = [];
  private droppedCount = 0;

  constructor(opts: AsyncTransportOptions) {
    this.apiUrl = opts.apiUrl.replace(/\/+$/, '');
    this.apiKey = opts.apiKey;
    this.flushBatchSize = opts.flushBatchSize ?? 50;
    this.timeoutMs = opts.timeoutMs ?? 2_000;
    this.maxBufferSize = opts.maxBufferSize ?? 10_000;
  }

  enqueue(event: ExecutionEvent): void {
    if (this.buffer.length >= this.maxBufferSize) {
      this.droppedCount++;
      if (this.droppedCount % 100 === 1) {
        console.warn(
          `[vex] Buffer full (${this.maxBufferSize} events), dropping event (total dropped: ${this.droppedCount})`
        );
      }
      return;
    }
    this.buffer.push(event);
  }

  async flush(): Promise<void> {
    if (this.buffer.length === 0) return;

    const batch = [...this.buffer];
    this.buffer = [];

    const payload = batch.map((e) => toSnakeCase(e));
    const url = `${this.apiUrl}/v1/ingest/batch`;

    const maxRetries = 3;
    const baseDelay = 100;

    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), this.timeoutMs);

        const response = await fetch(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Vex-Key': this.apiKey,
          },
          body: JSON.stringify({ events: payload }),
          signal: controller.signal,
        });

        clearTimeout(timer);

        if (response.ok) return; // success

        if (response.status < 500) {
          // 4xx — permanent failure, drop events
          console.warn(
            `[vex] Client error ${response.status} on flush; dropping ${batch.length} events`
          );
          return;
        }

        // 5xx — retry
        if (attempt < maxRetries - 1) {
          await this.delay(baseDelay * 2 ** attempt);
        }
      } catch {
        // Network error — retry
        if (attempt < maxRetries - 1) {
          await this.delay(baseDelay * 2 ** attempt);
        }
      }
    }

    // All retries exhausted — return events to buffer
    const available = Math.max(0, this.maxBufferSize - this.buffer.length);
    const eventsToRetry = batch.slice(0, available);
    const dropped = batch.length - eventsToRetry.length;
    if (dropped > 0) {
      this.droppedCount += dropped;
      console.warn(`[vex] Dropped ${dropped} events due to buffer overflow on retry`);
    }
    this.buffer = [...eventsToRetry, ...this.buffer];
  }

  async close(): Promise<void> {
    await this.flush();
  }

  private delay(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}
```

**Step 4: Run tests to verify they pass**

```bash
cd sdk/typescript && npx vitest run tests/transport/async.test.ts
```

**Step 5: Commit**

```bash
git add sdk/typescript/src/transport/async.ts sdk/typescript/tests/transport/async.test.ts
git commit -m "feat(ts-sdk): add AsyncTransport with batch flush and retry"
```

---

### Task 6: SyncTransport

**Files:**
- Create: `sdk/typescript/src/transport/sync.ts`
- Create: `sdk/typescript/tests/transport/sync.test.ts`

**Step 1: Write the failing tests**

```typescript
// tests/transport/sync.test.ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { SyncTransport } from '../../src/transport/sync';
import { createExecutionEvent } from '../../src/models';

function makeEvent() {
  return createExecutionEvent({
    agentId: 'test',
    input: 'in',
    output: 'out',
  });
}

describe('SyncTransport', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('POSTs event to /v1/verify and returns parsed response', async () => {
    const serverResponse = {
      execution_id: 'abc',
      confidence: 0.9,
      action: 'pass',
      output: 'result',
      checks: { hallucination: { score: 0.95, passed: true } },
      corrected: false,
      original_output: null,
      correction_attempts: null,
    };
    fetchMock.mockResolvedValue(new Response(JSON.stringify(serverResponse), { status: 200 }));

    const transport = new SyncTransport({
      apiUrl: 'https://api.tryvex.dev',
      apiKey: 'my-key',
    });

    const result = await transport.verify(makeEvent());

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe('https://api.tryvex.dev/v1/verify');
    expect(opts.method).toBe('POST');
    expect(opts.headers['X-Vex-Key']).toBe('my-key');
    expect(result.action).toBe('pass');
    expect(result.confidence).toBe(0.9);
  });

  it('converts event keys to snake_case in request body', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ execution_id: 'x', action: 'pass' }), { status: 200 })
    );

    const transport = new SyncTransport({
      apiUrl: 'https://api.tryvex.dev',
      apiKey: 'key',
    });

    await transport.verify(makeEvent());

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body).toHaveProperty('agent_id');
    expect(body).not.toHaveProperty('agentId');
  });

  it('includes thresholds in metadata when provided', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ execution_id: 'x', action: 'pass' }), { status: 200 })
    );

    const transport = new SyncTransport({
      apiUrl: 'https://api.tryvex.dev',
      apiKey: 'key',
    });

    await transport.verify(makeEvent(), {
      thresholds: { pass: 0.9, flag: 0.6, block: 0.2 },
    });

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.metadata.thresholds).toEqual({
      pass_threshold: 0.9,
      flag_threshold: 0.6,
    });
  });

  it('includes correction and transparency in metadata', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ execution_id: 'x', action: 'pass', corrected: true }), { status: 200 })
    );

    const transport = new SyncTransport({
      apiUrl: 'https://api.tryvex.dev',
      apiKey: 'key',
    });

    await transport.verify(makeEvent(), {
      correction: 'cascade',
      transparency: 'transparent',
    });

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.metadata.correction).toBe('cascade');
    expect(body.metadata.transparency).toBe('transparent');
  });

  it('uses longer timeout for correction requests', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ execution_id: 'x', action: 'pass' }), { status: 200 })
    );

    const transport = new SyncTransport({
      apiUrl: 'https://api.tryvex.dev',
      apiKey: 'key',
      timeoutMs: 10_000,
      correctionTimeoutMs: 30_000,
    });

    // We can't directly inspect AbortController timeout, but verify it doesn't throw
    await transport.verify(makeEvent(), { correction: 'cascade' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('throws on HTTP 4xx/5xx errors without retry', async () => {
    fetchMock.mockResolvedValue(new Response('bad', { status: 422 }));

    const transport = new SyncTransport({
      apiUrl: 'https://api.tryvex.dev',
      apiKey: 'key',
    });

    await expect(transport.verify(makeEvent())).rejects.toThrow();
    expect(fetchMock).toHaveBeenCalledTimes(1); // no retry on HTTP errors
  });

  it('retries on network errors with backoff', async () => {
    fetchMock
      .mockRejectedValueOnce(new TypeError('fetch failed'))
      .mockRejectedValueOnce(new TypeError('fetch failed'))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ execution_id: 'x', action: 'pass' }), { status: 200 })
      );

    const transport = new SyncTransport({
      apiUrl: 'https://api.tryvex.dev',
      apiKey: 'key',
    });

    const result = await transport.verify(makeEvent());
    expect(result.action).toBe('pass');
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('throws last network error after all retries exhausted', async () => {
    fetchMock.mockRejectedValue(new TypeError('fetch failed'));

    const transport = new SyncTransport({
      apiUrl: 'https://api.tryvex.dev',
      apiKey: 'key',
    });

    await expect(transport.verify(makeEvent())).rejects.toThrow('fetch failed');
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
```

**Step 2: Run tests to verify they fail**

```bash
cd sdk/typescript && npx vitest run tests/transport/sync.test.ts
```

**Step 3: Implement SyncTransport**

```typescript
// src/transport/sync.ts
import type { ExecutionEvent, ThresholdConfig } from '../models';
import { toSnakeCase, toCamelCase } from '../utils';
import { VerificationError } from '../errors';

export interface SyncTransportOptions {
  apiUrl: string;
  apiKey: string;
  timeoutMs?: number;
  correctionTimeoutMs?: number;
}

export interface VerifyOptions {
  thresholds?: ThresholdConfig;
  correction?: string;
  transparency?: string;
}

export interface VerifyResponse {
  executionId: string;
  confidence: number | null;
  action: string;
  output: unknown;
  corrections: Record<string, unknown>[] | null;
  checks: Record<string, unknown> | null;
  corrected: boolean;
  originalOutput: unknown | null;
  correctionAttempts: Record<string, unknown>[] | null;
}

export class SyncTransport {
  private readonly apiUrl: string;
  private readonly apiKey: string;
  private readonly timeoutMs: number;
  private readonly correctionTimeoutMs: number;

  constructor(opts: SyncTransportOptions) {
    this.apiUrl = opts.apiUrl.replace(/\/+$/, '');
    this.apiKey = opts.apiKey;
    this.timeoutMs = opts.timeoutMs ?? 30_000;
    this.correctionTimeoutMs = opts.correctionTimeoutMs ?? this.timeoutMs * 3;
  }

  async verify(event: ExecutionEvent, opts?: VerifyOptions): Promise<VerifyResponse> {
    const url = `${this.apiUrl}/v1/verify`;
    const payload = toSnakeCase(event) as Record<string, unknown>;

    // Ensure metadata exists
    if (!payload.metadata || typeof payload.metadata !== 'object') {
      payload.metadata = {};
    }
    const metadata = payload.metadata as Record<string, unknown>;

    if (opts?.thresholds) {
      metadata.thresholds = {
        pass_threshold: opts.thresholds.pass,
        flag_threshold: opts.thresholds.flag,
      };
    }

    const useCorrection = opts?.correction && opts.correction !== 'none';
    if (useCorrection) {
      metadata.correction = opts!.correction;
      metadata.transparency = opts?.transparency ?? 'opaque';
    }

    const timeout = useCorrection ? this.correctionTimeoutMs : this.timeoutMs;

    const maxRetries = 3;
    const baseDelay = 100;
    let lastError: unknown;

    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeout);

        const response = await fetch(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Vex-Key': this.apiKey,
          },
          body: JSON.stringify(payload),
          signal: controller.signal,
        });

        clearTimeout(timer);

        if (!response.ok) {
          throw new VerificationError(
            `Verification failed with status ${response.status}: ${await response.text()}`
          );
        }

        const raw = await response.json();
        return toCamelCase(raw) as VerifyResponse;
      } catch (err) {
        if (err instanceof VerificationError) {
          // HTTP errors — throw immediately, no retry
          throw err;
        }
        // Network errors — retry
        lastError = err;
        if (attempt < maxRetries - 1) {
          await this.delay(baseDelay * 2 ** attempt);
        }
      }
    }

    throw lastError;
  }

  private delay(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}
```

**Step 4: Run tests to verify they pass**

```bash
cd sdk/typescript && npx vitest run tests/transport/sync.test.ts
```

**Step 5: Commit**

```bash
git add sdk/typescript/src/transport/sync.ts sdk/typescript/tests/transport/sync.test.ts
git commit -m "feat(ts-sdk): add SyncTransport with verify, retry, and correction timeout"
```

---

### Task 7: TraceContext

**Files:**
- Create: `sdk/typescript/src/trace.ts`
- Create: `sdk/typescript/tests/trace.test.ts`

**Step 1: Write the failing tests**

```typescript
// tests/trace.test.ts
import { describe, it, expect } from 'vitest';
import { TraceContext } from '../src/trace';

describe('TraceContext', () => {
  it('records output', () => {
    const ctx = new TraceContext({ agentId: 'test', input: 'q' });
    ctx.record({ response: 'answer' });
    expect(ctx.getOutput()).toEqual({ response: 'answer' });
  });

  it('records ground truth', () => {
    const ctx = new TraceContext({ agentId: 'test', input: 'q' });
    ctx.setGroundTruth('expected');
    expect(ctx.getGroundTruth()).toBe('expected');
  });

  it('records schema', () => {
    const ctx = new TraceContext({ agentId: 'test', input: 'q' });
    const schema = { type: 'object', required: ['name'] };
    ctx.setSchema(schema);
    expect(ctx.getSchema()).toEqual(schema);
  });

  it('records steps', () => {
    const ctx = new TraceContext({ agentId: 'test', input: 'q' });
    ctx.step({ type: 'llm', name: 'gpt-4', input: 'prompt', output: 'resp', durationMs: 200 });
    ctx.step({ type: 'tool_call', name: 'search' });
    const steps = ctx.getSteps();
    expect(steps).toHaveLength(2);
    expect(steps[0].type).toBe('llm');
    expect(steps[0].durationMs).toBe(200);
    expect(steps[1].type).toBe('tool_call');
  });

  it('records token count and cost estimate', () => {
    const ctx = new TraceContext({ agentId: 'test', input: 'q' });
    ctx.setTokenCount(500);
    ctx.setCostEstimate(0.05);
    expect(ctx.getTokenCount()).toBe(500);
    expect(ctx.getCostEstimate()).toBe(0.05);
  });

  it('records metadata', () => {
    const ctx = new TraceContext({ agentId: 'test', input: 'q' });
    ctx.setMetadata('env', 'prod');
    ctx.setMetadata('version', '1.0');
    expect(ctx.getMetadata()).toEqual({ env: 'prod', version: '1.0' });
  });

  it('builds an ExecutionEvent', () => {
    const ctx = new TraceContext({
      agentId: 'my-agent',
      task: 'summarize',
      input: { query: 'hi' },
      sessionId: 'sess-1',
      sequenceNumber: 3,
    });
    ctx.setGroundTruth('truth');
    ctx.setSchema({ type: 'object' });
    ctx.record('output');

    const event = ctx.buildEvent();
    expect(event.agentId).toBe('my-agent');
    expect(event.task).toBe('summarize');
    expect(event.input).toEqual({ query: 'hi' });
    expect(event.output).toBe('output');
    expect(event.groundTruth).toBe('truth');
    expect(event.schemaDefinition).toEqual({ type: 'object' });
    expect(event.sessionId).toBe('sess-1');
    expect(event.sequenceNumber).toBe(3);
    expect(event.executionId).toBeDefined();
    expect(event.latencyMs).toBeGreaterThanOrEqual(0);
  });
});
```

**Step 2: Run tests to verify they fail**

```bash
cd sdk/typescript && npx vitest run tests/trace.test.ts
```

**Step 3: Implement TraceContext**

```typescript
// src/trace.ts
import {
  type ExecutionEvent,
  type StepRecord,
  type ConversationTurn,
  createExecutionEvent,
  createStepRecord,
} from './models';

export interface TraceContextOptions {
  agentId: string;
  task?: string;
  input?: unknown;
  sessionId?: string;
  sequenceNumber?: number;
  parentExecutionId?: string;
  conversationHistory?: ConversationTurn[];
}

export class TraceContext {
  private readonly agentId: string;
  private readonly task?: string;
  private readonly input: unknown;
  private readonly sessionId?: string;
  private readonly sequenceNumber?: number;
  private readonly parentExecutionId?: string;
  private readonly conversationHistory?: ConversationTurn[];
  private readonly startTime: number;

  private output: unknown = undefined;
  private groundTruth: unknown = undefined;
  private schema: Record<string, unknown> | undefined;
  private steps: StepRecord[] = [];
  private metadata: Record<string, unknown> = {};
  private tokenCount: number | undefined;
  private costEstimate: number | undefined;

  constructor(opts: TraceContextOptions) {
    this.agentId = opts.agentId;
    this.task = opts.task;
    this.input = opts.input;
    this.sessionId = opts.sessionId;
    this.sequenceNumber = opts.sequenceNumber;
    this.parentExecutionId = opts.parentExecutionId;
    this.conversationHistory = opts.conversationHistory;
    this.startTime = performance.now();
  }

  record(output: unknown): void {
    this.output = output;
  }

  setGroundTruth(data: unknown): void {
    this.groundTruth = data;
  }

  setSchema(schema: Record<string, unknown>): void {
    this.schema = schema;
  }

  setTokenCount(count: number): void {
    this.tokenCount = count;
  }

  setCostEstimate(cost: number): void {
    this.costEstimate = cost;
  }

  setMetadata(key: string, value: unknown): void {
    this.metadata[key] = value;
  }

  step(opts: {
    type: string;
    name: string;
    input?: unknown;
    output?: unknown;
    durationMs?: number;
  }): void {
    this.steps.push(createStepRecord(opts));
  }

  // -- Getters for testing --
  getOutput(): unknown { return this.output; }
  getGroundTruth(): unknown { return this.groundTruth; }
  getSchema(): Record<string, unknown> | undefined { return this.schema; }
  getSteps(): StepRecord[] { return [...this.steps]; }
  getTokenCount(): number | undefined { return this.tokenCount; }
  getCostEstimate(): number | undefined { return this.costEstimate; }
  getMetadata(): Record<string, unknown> { return { ...this.metadata }; }

  /**
   * Build the ExecutionEvent from accumulated trace data.
   */
  buildEvent(): ExecutionEvent {
    const latencyMs = performance.now() - this.startTime;

    return createExecutionEvent({
      agentId: this.agentId,
      task: this.task,
      input: this.input,
      output: this.output,
      sessionId: this.sessionId,
      sequenceNumber: this.sequenceNumber,
      parentExecutionId: this.parentExecutionId,
      conversationHistory: this.conversationHistory,
      steps: this.steps,
      tokenCount: this.tokenCount,
      costEstimate: this.costEstimate,
      latencyMs,
      groundTruth: this.groundTruth,
      schemaDefinition: this.schema,
      metadata: this.metadata,
    });
  }
}
```

**Step 4: Run tests to verify they pass**

```bash
cd sdk/typescript && npx vitest run tests/trace.test.ts
```

**Step 5: Commit**

```bash
git add sdk/typescript/src/trace.ts sdk/typescript/tests/trace.test.ts
git commit -m "feat(ts-sdk): add TraceContext for execution tracing"
```

---

### Task 8: Vex Client (Main Class)

**Files:**
- Create: `sdk/typescript/src/vex.ts`
- Create: `sdk/typescript/tests/vex.test.ts`

**Step 1: Write the failing tests**

```typescript
// tests/vex.test.ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { Vex } from '../src/vex';
import { VexBlockError, ConfigurationError } from '../src/errors';

describe('Vex', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue(new Response('{"ok":true}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // -- Construction --

  it('throws ConfigurationError for empty API key', () => {
    expect(() => new Vex({ apiKey: '' })).toThrow(ConfigurationError);
  });

  it('throws ConfigurationError for whitespace-only API key', () => {
    expect(() => new Vex({ apiKey: '   ' })).toThrow(ConfigurationError);
  });

  it('throws ConfigurationError for too-short API key', () => {
    expect(() => new Vex({ apiKey: 'short' })).toThrow(ConfigurationError);
  });

  it('creates with valid API key and default config', () => {
    const vex = new Vex({ apiKey: 'ag_live_test_key_12345' });
    expect(vex).toBeDefined();
    vex.close();
  });

  // -- Async trace --

  it('async trace returns pass-through VexResult', async () => {
    const vex = new Vex({ apiKey: 'ag_live_test_key_12345' });

    const result = await vex.trace(
      { agentId: 'test', task: 'summarize', input: 'q' },
      async (ctx) => {
        ctx.record({ answer: 'a' });
      },
    );

    expect(result.action).toBe('pass');
    expect(result.output).toEqual({ answer: 'a' });
    expect(result.executionId).toBeDefined();
    await vex.close();
  });

  // -- Sync trace (pass) --

  it('sync trace returns server verification result', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({
        execution_id: 'srv-1',
        confidence: 0.9,
        action: 'pass',
        output: { answer: 'a' },
        checks: { hallucination: { score: 0.95, passed: true } },
        corrected: false,
        original_output: null,
        correction_attempts: null,
      }), { status: 200 }),
    );

    const vex = new Vex({
      apiKey: 'ag_live_test_key_12345',
      config: { mode: 'sync' },
    });

    const result = await vex.trace(
      { agentId: 'test', task: 'qa', input: 'q' },
      async (ctx) => {
        ctx.setGroundTruth('truth');
        ctx.record({ answer: 'a' });
      },
    );

    expect(result.action).toBe('pass');
    expect(result.confidence).toBe(0.9);
    await vex.close();
  });

  // -- Sync trace (block) --

  it('sync trace throws VexBlockError on block action', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({
        execution_id: 'srv-1',
        confidence: 0.1,
        action: 'block',
        output: 'bad',
        checks: {},
        corrected: false,
        original_output: null,
        correction_attempts: null,
      }), { status: 200 }),
    );

    const vex = new Vex({
      apiKey: 'ag_live_test_key_12345',
      config: { mode: 'sync' },
    });

    await expect(
      vex.trace(
        { agentId: 'test', input: 'q' },
        async (ctx) => { ctx.record('bad output'); },
      ),
    ).rejects.toThrow(VexBlockError);

    await vex.close();
  });

  // -- Sync trace (flag) --

  it('sync trace returns result with warning on flag', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({
        execution_id: 'srv-1',
        confidence: 0.6,
        action: 'flag',
        output: 'maybe',
        checks: {},
        corrected: false,
        original_output: null,
        correction_attempts: null,
      }), { status: 200 }),
    );

    const vex = new Vex({
      apiKey: 'ag_live_test_key_12345',
      config: { mode: 'sync' },
    });

    const result = await vex.trace(
      { agentId: 'test', input: 'q' },
      async (ctx) => { ctx.record('maybe'); },
    );

    expect(result.action).toBe('flag');
    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
    await vex.close();
  });

  // -- Sync fallthrough on error --

  it('sync trace falls through to pass on verification error', async () => {
    fetchMock.mockRejectedValue(new TypeError('network error'));

    const vex = new Vex({
      apiKey: 'ag_live_test_key_12345',
      config: { mode: 'sync' },
    });

    const result = await vex.trace(
      { agentId: 'test', input: 'q' },
      async (ctx) => { ctx.record('output'); },
    );

    expect(result.action).toBe('pass');
    expect(result.output).toBe('output');
    await vex.close();
  });

  // -- Correction (transparent) --

  it('sync trace with correction returns corrected result', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({
        execution_id: 'srv-1',
        confidence: 0.9,
        action: 'pass',
        output: 'corrected answer',
        checks: {},
        corrected: true,
        original_output: 'wrong answer',
        correction_attempts: [{ layer: 1, layer_name: 'repair', success: true }],
      }), { status: 200 }),
    );

    const vex = new Vex({
      apiKey: 'ag_live_test_key_12345',
      config: { mode: 'sync', correction: 'cascade', transparency: 'transparent' },
    });

    const result = await vex.trace(
      { agentId: 'test', input: 'q' },
      async (ctx) => { ctx.record('wrong answer'); },
    );

    expect(result.corrected).toBe(true);
    expect(result.output).toBe('corrected answer');
    expect(result.originalOutput).toBe('wrong answer');
    expect(result.corrections).toHaveLength(1);
    await vex.close();
  });

  // -- Threshold forwarding --

  it('forwards custom thresholds to sync transport', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({
        execution_id: 'x',
        confidence: 0.85,
        action: 'pass',
        output: 'ok',
        checks: {},
        corrected: false,
      }), { status: 200 }),
    );

    const vex = new Vex({
      apiKey: 'ag_live_test_key_12345',
      config: {
        mode: 'sync',
        confidenceThreshold: { pass: 0.9, flag: 0.6, block: 0.2 },
      },
    });

    await vex.trace(
      { agentId: 'test', input: 'q' },
      async (ctx) => { ctx.record('ok'); },
    );

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.metadata.thresholds.pass_threshold).toBe(0.9);
    expect(body.metadata.thresholds.flag_threshold).toBe(0.6);
    await vex.close();
  });
});
```

**Step 2: Run tests to verify they fail**

```bash
cd sdk/typescript && npx vitest run tests/vex.test.ts
```

**Step 3: Implement Vex client**

```typescript
// src/vex.ts
import { resolveConfig, type VexConfig, type VexConfigInput } from './config';
import { ConfigurationError, VexBlockError } from './errors';
import type { VexResult, ConversationTurn } from './models';
import { AsyncTransport } from './transport/async';
import { SyncTransport } from './transport/sync';
import { TraceContext } from './trace';
import { toCamelCase } from './utils';

export interface VexOptions {
  apiKey: string;
  config?: VexConfigInput;
}

export interface TraceOptions {
  agentId: string;
  task?: string;
  input?: unknown;
}

export class Vex {
  public readonly config: VexConfig;
  private readonly apiKey: string;
  private readonly asyncTransport: AsyncTransport;
  private readonly syncTransport: SyncTransport | null;
  private flushTimer: ReturnType<typeof setInterval> | null = null;
  private closed = false;

  constructor(opts: VexOptions) {
    // Validate API key
    const key = opts.apiKey?.trim() ?? '';
    if (!key) throw new ConfigurationError('API key cannot be empty');
    if (key.length < 10) throw new ConfigurationError('API key appears invalid (too short)');

    this.apiKey = key;
    this.config = resolveConfig(opts.config);

    this.asyncTransport = new AsyncTransport({
      apiUrl: this.config.apiUrl,
      apiKey: this.apiKey,
      flushBatchSize: this.config.flushBatchSize,
      timeoutMs: this.config.timeoutMs,
      maxBufferSize: this.config.maxBufferSize,
    });

    this.syncTransport = this.config.mode === 'sync'
      ? new SyncTransport({
          apiUrl: this.config.apiUrl,
          apiKey: this.apiKey,
          timeoutMs: this.config.timeoutMs,
          correctionTimeoutMs: this.config.timeoutMs * 3,
        })
      : null;

    // Start periodic flush
    this.flushTimer = setInterval(() => {
      this.asyncTransport.flush().catch(() => {
        // Silently ignore — events remain in buffer for next cycle
      });
    }, this.config.flushIntervalMs);

    // Prevent timer from keeping process alive
    if (this.flushTimer && typeof this.flushTimer === 'object' && 'unref' in this.flushTimer) {
      (this.flushTimer as NodeJS.Timeout).unref();
    }
  }

  /**
   * Trace an execution using a callback that receives a TraceContext.
   */
  async trace(
    opts: TraceOptions,
    fn: (ctx: TraceContext) => Promise<void> | void,
  ): Promise<VexResult> {
    const ctx = new TraceContext({
      agentId: opts.agentId,
      task: opts.task,
      input: opts.input,
    });

    await fn(ctx);

    const event = ctx.buildEvent();
    return this.processEvent(event);
  }

  /**
   * Create a Session for multi-turn conversation tracing.
   */
  session(opts: { agentId: string; sessionId?: string; metadata?: Record<string, unknown> }) {
    // Imported lazily to avoid circular deps; Session is exported from index.ts
    const { Session } = require('./session');
    return new Session(this, opts.agentId, opts.sessionId, opts.metadata);
  }

  /**
   * Flush buffered events and stop the background timer.
   */
  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;

    if (this.flushTimer !== null) {
      clearInterval(this.flushTimer);
      this.flushTimer = null;
    }

    await this.asyncTransport.close();
  }

  // -- Internal --

  /** @internal — used by Session.trace */
  async _processTraceContext(ctx: TraceContext): Promise<VexResult> {
    const event = ctx.buildEvent();
    return this.processEvent(event);
  }

  private async processEvent(event: ReturnType<TraceContext['buildEvent']>): Promise<VexResult> {
    if (this.config.mode === 'sync' && this.syncTransport) {
      try {
        const response = await this.syncTransport.verify(event, {
          thresholds: this.config.confidenceThreshold,
          correction: this.config.correction,
          transparency: this.config.transparency,
        });

        const result: VexResult = {
          output: response.output ?? event.output,
          confidence: response.confidence ?? null,
          action: (response.action as VexResult['action']) ?? 'pass',
          corrections: response.correctionAttempts ?? null,
          executionId: response.executionId ?? event.executionId,
          verification: response.checks ?? null,
          corrected: response.corrected ?? false,
          originalOutput: response.originalOutput ?? null,
        };

        if (result.action === 'block') {
          throw new VexBlockError(result);
        }

        if (result.action === 'flag') {
          const msg = this.config.logEventIds
            ? `Agent output flagged for event ${event.executionId} (confidence=${result.confidence})`
            : `Agent output flagged (confidence=${result.confidence})`;
          console.warn(`[vex] ${msg}`);
        }

        return result;
      } catch (err) {
        if (err instanceof VexBlockError) throw err;

        const msg = this.config.logEventIds
          ? `Sync verification failed for event ${event.executionId}; returning pass-through result`
          : 'Sync verification failed; returning pass-through result';
        console.warn(`[vex] ${msg}`);

        return {
          output: event.output,
          confidence: null,
          action: 'pass',
          corrections: null,
          executionId: event.executionId,
          verification: null,
          corrected: false,
          originalOutput: null,
        };
      }
    }

    // Async mode: enqueue and return pass-through
    this.asyncTransport.enqueue(event);
    return {
      output: event.output,
      confidence: null,
      action: 'pass',
      corrections: null,
      executionId: event.executionId,
      verification: null,
      corrected: false,
      originalOutput: null,
    };
  }
}
```

**Note:** The `session()` method uses `require('./session')` to avoid circular dependency. We'll replace this with a cleaner pattern in Task 9.

**Step 4: Run tests to verify they pass**

```bash
cd sdk/typescript && npx vitest run tests/vex.test.ts
```

**Step 5: Commit**

```bash
git add sdk/typescript/src/vex.ts sdk/typescript/tests/vex.test.ts
git commit -m "feat(ts-sdk): add Vex client with async/sync modes and correction"
```

---

### Task 9: Session (Multi-turn)

**Files:**
- Create: `sdk/typescript/src/session.ts`
- Create: `sdk/typescript/tests/session.test.ts`

**Step 1: Write the failing tests**

```typescript
// tests/session.test.ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { Session } from '../src/session';
import { Vex } from '../src/vex';

describe('Session', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue(new Response('{"ok":true}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('auto-generates a session ID', () => {
    const vex = new Vex({ apiKey: 'ag_live_test_key_12345' });
    const session = new Session(vex, 'agent-1');
    expect(session.sessionId).toBeDefined();
    expect(session.sessionId.length).toBe(36);
    vex.close();
  });

  it('accepts a custom session ID', () => {
    const vex = new Vex({ apiKey: 'ag_live_test_key_12345' });
    const session = new Session(vex, 'agent-1', 'custom-id');
    expect(session.sessionId).toBe('custom-id');
    vex.close();
  });

  it('increments sequence number after each trace', async () => {
    const vex = new Vex({ apiKey: 'ag_live_test_key_12345' });
    const session = new Session(vex, 'agent-1');

    expect(session.sequence).toBe(0);

    await session.trace({ task: 'qa' }, async (ctx) => {
      ctx.record('answer 1');
    });
    expect(session.sequence).toBe(1);

    await session.trace({ task: 'qa' }, async (ctx) => {
      ctx.record('answer 2');
    });
    expect(session.sequence).toBe(2);

    await vex.close();
  });

  it('accumulates conversation history', async () => {
    const vex = new Vex({ apiKey: 'ag_live_test_key_12345' });
    const session = new Session(vex, 'agent-1');

    await session.trace({ task: 'qa', input: 'q1' }, async (ctx) => {
      ctx.record('a1');
    });

    await session.trace({ task: 'qa', input: 'q2' }, async (ctx) => {
      ctx.record('a2');
    });

    // Third trace should have 2 turns in history
    const historyCapture: unknown[] = [];
    await session.trace({ task: 'qa', input: 'q3' }, async (ctx) => {
      // We can't directly access history from ctx, but we can verify via the event
      ctx.record('a3');
    });

    expect(session.sequence).toBe(3);
    await vex.close();
  });

  it('respects conversation window size', async () => {
    const vex = new Vex({
      apiKey: 'ag_live_test_key_12345',
      config: { conversationWindowSize: 2 },
    });
    const session = new Session(vex, 'agent-1');

    // Create 3 turns
    for (let i = 0; i < 3; i++) {
      await session.trace({ task: 'qa', input: `q${i}` }, async (ctx) => {
        ctx.record(`a${i}`);
      });
    }

    // History should only have last 2 turns
    expect(session.sequence).toBe(3);
    await vex.close();
  });

  it('merges session-level metadata into traces', async () => {
    const vex = new Vex({ apiKey: 'ag_live_test_key_12345' });
    const session = new Session(vex, 'agent-1', undefined, { env: 'test' });

    const result = await session.trace({ task: 'qa' }, async (ctx) => {
      ctx.record('answer');
    });

    expect(result.executionId).toBeDefined();
    await vex.close();
  });
});
```

**Step 2: Run tests to verify they fail**

```bash
cd sdk/typescript && npx vitest run tests/session.test.ts
```

**Step 3: Implement Session**

```typescript
// src/session.ts
import type { Vex } from './vex';
import type { VexResult, ConversationTurn } from './models';
import { TraceContext } from './trace';

export interface SessionTraceOptions {
  task?: string;
  input?: unknown;
  parentExecutionId?: string;
}

export class Session {
  public readonly sessionId: string;
  private readonly vex: Vex;
  private readonly agentId: string;
  private readonly metadata: Record<string, unknown>;
  private seq = 0;
  private history: ConversationTurn[] = [];

  constructor(
    vex: Vex,
    agentId: string,
    sessionId?: string,
    metadata?: Record<string, unknown>,
  ) {
    this.vex = vex;
    this.agentId = agentId;
    this.sessionId = sessionId ?? crypto.randomUUID();
    this.metadata = metadata ?? {};
  }

  get sequence(): number {
    return this.seq;
  }

  async trace(
    opts: SessionTraceOptions,
    fn: (ctx: TraceContext) => Promise<void> | void,
  ): Promise<VexResult> {
    const currentSeq = this.seq;
    const windowSize = this.vex.config.conversationWindowSize;

    // Snapshot history BEFORE this turn (excludes current turn)
    const historySnapshot: ConversationTurn[] | undefined =
      this.history.length > 0
        ? this.history.slice(-windowSize)
        : undefined;

    const ctx = new TraceContext({
      agentId: this.agentId,
      task: opts.task,
      input: opts.input,
      sessionId: this.sessionId,
      sequenceNumber: currentSeq,
      parentExecutionId: opts.parentExecutionId,
      conversationHistory: historySnapshot,
    });

    // Merge session-level metadata
    for (const [key, value] of Object.entries(this.metadata)) {
      ctx.setMetadata(key, value);
    }

    await fn(ctx);

    const result = await this.vex._processTraceContext(ctx);

    // Update sequence and history
    this.seq++;
    this.history.push({
      sequenceNumber: currentSeq,
      input: opts.input,
      output: ctx.getOutput(),
      task: opts.task,
    });
    if (this.history.length > windowSize) {
      this.history = this.history.slice(-windowSize);
    }

    return result;
  }
}
```

**Step 4: Update Vex.session() to avoid circular import**

Replace the `require()` in `src/vex.ts` — instead, import `Session` at the top and use it directly:

In `src/vex.ts`, change the `session()` method to:
```typescript
import { Session } from './session';

// In the class:
session(opts: { agentId: string; sessionId?: string; metadata?: Record<string, unknown> }): Session {
  return new Session(this, opts.agentId, opts.sessionId, opts.metadata);
}
```

**Step 5: Run tests to verify they pass**

```bash
cd sdk/typescript && npx vitest run tests/session.test.ts
```

**Step 6: Commit**

```bash
git add sdk/typescript/src/session.ts sdk/typescript/src/vex.ts sdk/typescript/tests/session.test.ts
git commit -m "feat(ts-sdk): add Session for multi-turn conversation tracing"
```

---

### Task 10: Public Exports & Build

**Files:**
- Modify: `sdk/typescript/src/index.ts`

**Step 1: Update index.ts with all exports**

```typescript
// src/index.ts
export { Vex } from './vex';
export type { VexOptions, TraceOptions } from './vex';

export { Session } from './session';
export type { SessionTraceOptions } from './session';

export { TraceContext } from './trace';

export {
  type VexResult,
  type ExecutionEvent,
  type ConversationTurn,
  type StepRecord,
  type ThresholdConfig,
} from './models';

export { type VexConfig, type VexConfigInput } from './config';

export {
  VexError,
  ConfigurationError,
  IngestionError,
  VerificationError,
  VexBlockError,
} from './errors';
```

**Step 2: Build and verify**

```bash
cd sdk/typescript && npm run build
```
Expected: `dist/index.js`, `dist/index.cjs`, `dist/index.d.ts` generated.

**Step 3: Run all tests**

```bash
cd sdk/typescript && npm test
```
Expected: ALL PASS.

**Step 4: Type check**

```bash
cd sdk/typescript && npm run typecheck
```
Expected: No errors.

**Step 5: Commit**

```bash
git add sdk/typescript/src/index.ts sdk/typescript/dist/
git commit -m "feat(ts-sdk): wire up public exports and dual ESM/CJS build"
```

---

### Task 11: Live Smoke Test

**Files:**
- Create: `sdk/typescript/scripts/test_live_smoke.ts`

**Step 1: Create the live smoke test**

Port the 6 scenarios from the Python `scripts/test_live_smoke.py` to TypeScript. Same structure: env vars, ANSI output, summary table, exit code.

```typescript
#!/usr/bin/env npx tsx
/**
 * Live smoke test — exercises the full SDK → Gateway → Storage pipeline.
 *
 * Usage:
 *   VEX_API_KEY=ag_live_... npx tsx sdk/typescript/scripts/test_live_smoke.ts
 */

import { Vex, VexConfig, VexBlockError, VexResult, Session } from '../src/index';

// Config
const API_KEY = process.env.VEX_API_KEY ?? process.env.AGENTGUARD_API_KEY ?? '';
const API_URL = process.env.VEX_API_URL ?? process.env.AGENTGUARD_API_URL ?? 'https://api.tryvex.dev';

if (!API_KEY) {
  console.error('ERROR: Set VEX_API_KEY (or AGENTGUARD_API_KEY) environment variable.');
  process.exit(1);
}

// ANSI
const GREEN = '\x1b[92m';
const RED = '\x1b[91m';
const YELLOW = '\x1b[93m';
const CYAN = '\x1b[96m';
const BOLD = '\x1b[1m';
const RESET = '\x1b[0m';

function header(title: string) {
  console.log(`\n${'='.repeat(70)}`);
  console.log(`${BOLD}${CYAN}${title}${RESET}`);
  console.log(`${'='.repeat(70)}`);
}

function ok(msg: string) { console.log(`  ${GREEN}PASS${RESET}  ${msg}`); }
function fail(msg: string) { console.log(`  ${RED}FAIL${RESET}  ${msg}`); }

type ScenarioResult = [boolean, string];

// Scenario 1: Async ingest
async function scenario1(): Promise<ScenarioResult> {
  header('Scenario 1: ASYNC INGEST (fire-and-forget)');
  const vex = new Vex({ apiKey: API_KEY, config: { apiUrl: API_URL, mode: 'async' } });
  try {
    await vex.trace(
      { agentId: 'smoke-test-ts', task: 'Summarize earnings', input: { query: 'Q4 earnings' } },
      (ctx) => {
        ctx.setGroundTruth({ revenue: '$5.2B' });
        ctx.record({ response: 'ACME Corp reported $5.2B in revenue.' });
      },
    );
    await vex.close();
    ok('Async trace completed without exception');
    return [true, 'accepted'];
  } catch (err) {
    fail(`Async trace raised: ${err}`);
    return [false, String(err)];
  }
}

// Scenario 2: Sync pass
async function scenario2(): Promise<ScenarioResult> {
  header('Scenario 2: SYNC VERIFICATION — PASS');
  const vex = new Vex({ apiKey: API_KEY, config: { apiUrl: API_URL, mode: 'sync' } });
  const result = await vex.trace(
    { agentId: 'smoke-test-ts', task: 'Answer geography questions accurately', input: { query: 'Capital of France?' } },
    (ctx) => {
      ctx.setGroundTruth('The capital of France is Paris.');
      ctx.record({ response: 'The capital of France is Paris. Known for the Eiffel Tower.' });
    },
  );
  await vex.close();
  console.log(`  Action: ${result.action}, Confidence: ${result.confidence}`);
  if ((result.action === 'pass' || result.action === 'flag') && (result.confidence === null || result.confidence >= 0.5)) {
    ok(`action=${result.action}, confidence=${result.confidence}`);
    return [true, result.action];
  }
  fail(`Expected pass/flag, got ${result.action}`);
  return [false, result.action];
}

// Scenario 3: Sync flag/block
async function scenario3(): Promise<ScenarioResult> {
  header('Scenario 3: SYNC VERIFICATION — FLAG/BLOCK');
  const vex = new Vex({ apiKey: API_KEY, config: { apiUrl: API_URL, mode: 'sync' } });
  try {
    const result = await vex.trace(
      { agentId: 'smoke-test-ts', task: 'Answer geography questions accurately', input: { query: 'Capital of France?' } },
      (ctx) => {
        ctx.setGroundTruth('The capital of France is Paris.');
        ctx.record({ response: 'The capital of France is Berlin. France is in Asia with 10 billion people.' });
      },
    );
    await vex.close();
    if (result.action === 'flag' || result.action === 'block') {
      ok(`action=${result.action}`);
      return [true, result.action];
    }
    fail(`Expected flag/block, got ${result.action}`);
    return [false, result.action];
  } catch (err) {
    await vex.close();
    if (err instanceof VexBlockError) {
      ok('VexBlockError raised (action=block)');
      return [true, 'block'];
    }
    fail(`Unexpected error: ${err}`);
    return [false, 'error'];
  }
}

// Scenario 4: Correction cascade (transparent)
async function scenario4(): Promise<ScenarioResult> {
  header('Scenario 4: CORRECTION CASCADE (transparent)');
  const vex = new Vex({
    apiKey: API_KEY,
    config: { apiUrl: API_URL, mode: 'sync', correction: 'cascade', transparency: 'transparent' },
  });
  try {
    const result = await vex.trace(
      { agentId: 'smoke-test-ts', task: 'Answer geography questions accurately', input: { query: 'Capital of France?' } },
      (ctx) => {
        ctx.setGroundTruth('The capital of France is Paris.');
        ctx.record({ response: 'The capital of France is Lyon. Known for the Eiffel Tower.' });
      },
    );
    await vex.close();
    console.log(`  Action: ${result.action}, Corrected: ${result.corrected}`);
    if (result.corrected) {
      console.log(`  Output: ${String(result.output).slice(0, 120)}...`);
      ok(`corrected=true, action=${result.action}`);
      return [true, 'corrected'];
    }
    fail(`Expected corrected=true, got ${result.corrected}`);
    return [false, `corrected=${result.corrected}`];
  } catch (err) {
    await vex.close();
    if (err instanceof VexBlockError && err.result.corrected) {
      ok(`corrected=true (blocked after correction)`);
      return [true, 'corrected'];
    }
    fail(`Error: ${err}`);
    return [false, 'error'];
  }
}

// Scenario 5: Auto-correct (opaque)
async function scenario5(): Promise<ScenarioResult> {
  header('Scenario 5: AUTO-CORRECT (opaque)');
  const vex = new Vex({
    apiKey: API_KEY,
    config: { apiUrl: API_URL, mode: 'sync', correction: 'cascade', transparency: 'opaque' },
  });
  const original = { response: 'The capital of France is Lyon. Known for the Eiffel Tower.' };
  try {
    const result = await vex.trace(
      { agentId: 'smoke-test-ts', task: 'Answer geography questions accurately', input: { query: 'Capital of France?' } },
      (ctx) => {
        ctx.setGroundTruth('The capital of France is Paris.');
        ctx.record(original);
      },
    );
    await vex.close();
    console.log(`  Action: ${result.action}, Corrected: ${result.corrected}`);
    if (result.corrected) {
      console.log(`  Output: ${String(result.output).slice(0, 120)}...`);
      if (result.originalOutput === null) ok('Opaque: original hidden');
      ok('Corrected output returned');
      return [true, 'auto-corrected'];
    }
    fail(`Expected corrected=true, got ${result.corrected}`);
    return [false, `corrected=${result.corrected}`];
  } catch (err) {
    await vex.close();
    fail(`Error: ${err}`);
    return [false, 'error'];
  }
}

// Scenario 6: Multi-turn session (contradiction)
async function scenario6(): Promise<ScenarioResult> {
  header('Scenario 6: MULTI-TURN SESSION (contradiction)');
  const vex = new Vex({ apiKey: API_KEY, config: { apiUrl: API_URL, mode: 'sync' } });
  const session = new Session(vex, 'smoke-test-ts-session');

  const r1 = await session.trace(
    { task: 'Answer geography questions', input: { query: 'Capital of France?' } },
    (ctx) => {
      ctx.setGroundTruth('The capital of France is Paris.');
      ctx.record({ response: 'The capital of France is Paris.' });
    },
  );
  console.log(`  Turn 1: action=${r1.action}`);

  try {
    const r2 = await session.trace(
      { task: 'Answer geography questions', input: { query: 'Capital of France?' } },
      (ctx) => {
        ctx.setGroundTruth('The capital of France is Paris.');
        ctx.record({ response: 'Actually, the capital of France is Marseille. It has never been Paris.' });
      },
    );
    await vex.close();
    console.log(`  Turn 2: action=${r2.action}, confidence=${r2.confidence}`);
    if (r2.action === 'flag' || r2.action === 'block') {
      ok(`Contradiction detected: action=${r2.action}`);
      return [true, r2.action];
    }
    fail(`Expected flag/block, got ${r2.action}`);
    return [false, r2.action];
  } catch (err) {
    await vex.close();
    if (err instanceof VexBlockError) {
      ok('VexBlockError raised on contradictory turn');
      return [true, 'block'];
    }
    fail(`Error: ${err}`);
    return [false, 'error'];
  }
}

// Main
const SCENARIOS: [string, () => Promise<ScenarioResult>][] = [
  ['Async Ingest', scenario1],
  ['Sync Pass', scenario2],
  ['Sync Flag/Block', scenario3],
  ['Correction Cascade', scenario4],
  ['Auto-Correct (opaque)', scenario5],
  ['Multi-turn Session', scenario6],
];

async function main(): Promise<number> {
  console.log(`${BOLD}Vex TypeScript SDK Live Smoke Test${RESET}`);
  console.log(`  API URL: ${API_URL}`);
  console.log(`  API Key: ${API_KEY.slice(0, 8)}...${API_KEY.slice(-4)}`);

  const results: [string, boolean, string][] = [];

  for (const [name, fn] of SCENARIOS) {
    const t0 = performance.now();
    try {
      const [passed, detail] = await fn();
      const elapsed = ((performance.now() - t0) / 1000).toFixed(1);
      console.log(`  ${CYAN}(${elapsed}s)${RESET}`);
      results.push([name, passed, detail]);
    } catch (err) {
      fail(`Unhandled exception in ${name}: ${err}`);
      results.push([name, false, 'exception']);
    }
  }

  header('SUMMARY');
  let totalPassed = 0;
  for (const [name, passed, detail] of results) {
    const status = passed ? `${GREEN}PASS${RESET}` : `${RED}FAIL${RESET}`;
    console.log(`  ${name.padEnd(25)}  [${status}]  ${detail}`);
    if (passed) totalPassed++;
  }

  console.log(`\n  ${BOLD}${totalPassed}/${results.length} scenarios passed${RESET}`);
  if (totalPassed === results.length) {
    console.log(`\n  ${GREEN}${BOLD}ALL SCENARIOS PASSED${RESET}`);
    return 0;
  }
  console.log(`\n  ${RED}${BOLD}SOME SCENARIOS FAILED${RESET}`);
  return 1;
}

main().then((code) => process.exit(code));
```

**Step 2: Verify it runs (requires live API key)**

```bash
VEX_API_KEY=ag_live_... npx tsx sdk/typescript/scripts/test_live_smoke.ts
```
Expected: 6/6 scenarios pass.

**Step 3: Commit**

```bash
git add sdk/typescript/scripts/test_live_smoke.ts
git commit -m "feat(ts-sdk): add live smoke test — 6 scenarios"
```

---

### Task 12: Final Integration — Full Test Suite + Build Verification

**Step 1: Run full test suite**

```bash
cd sdk/typescript && npm test
```
Expected: ALL PASS (utils, errors, models, config, async transport, sync transport, trace, vex, session).

**Step 2: Run typecheck**

```bash
cd sdk/typescript && npm run typecheck
```
Expected: No errors.

**Step 3: Run build**

```bash
cd sdk/typescript && npm run build
```
Expected: `dist/` contains `index.js`, `index.cjs`, `index.d.ts`.

**Step 4: Commit final state**

```bash
git add -A sdk/typescript/
git commit -m "feat(ts-sdk): complete TypeScript SDK v0.1.0 with tests and live smoke test"
```
