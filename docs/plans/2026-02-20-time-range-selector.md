# Time Range Selector Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a time range selector (1h, 24h, 7d, 30d) to 4 dashboard pages that currently have hardcoded time windows.

**Architecture:** Shared `time-range.ts` utility + `TimeRangeSelect` client component. Each page reads `?timeRange=` from URL search params, passes to loaders. Loaders default to their current hardcoded values when no param is provided (zero behavior change without the param).

**Tech Stack:** Next.js 16 (App Router), React 19, TypeScript, `useSearchParams`/`useRouter` from `next/navigation`

---

### Task 1: Shared Time Range Utility

**Files:**
- Create: `apps/web/lib/agentguard/time-range.ts`

**Step 1: Create the shared utility**

```typescript
export type TimeRange = '1h' | '24h' | '7d' | '30d';

export const TIME_RANGE_INTERVALS: Record<TimeRange, string> = {
  '1h': '1 hour',
  '24h': '24 hours',
  '7d': '7 days',
  '30d': '30 days',
};

export const TIME_RANGE_OPTIONS: { value: TimeRange; label: string }[] = [
  { value: '1h', label: 'Last 1 hour' },
  { value: '24h', label: 'Last 24 hours' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
];

export function parseTimeRange(raw: string | undefined): TimeRange | undefined {
  if (raw === '1h' || raw === '24h' || raw === '7d' || raw === '30d') return raw;
  return undefined;
}
```

**Step 2: Commit**

```bash
git add apps/web/lib/agentguard/time-range.ts
git commit -m "feat: add shared time range utility"
```

---

### Task 2: Shared TimeRangeSelect Component

**Files:**
- Create: `apps/web/components/time-range-select.tsx`

**Step 1: Create the client component**

Follow the exact pattern from `alerts-charts.tsx` (lines 57-77, 132-155) but as a standalone reusable component:

```typescript
'use client';

import { useCallback } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { TIME_RANGE_OPTIONS } from '~/lib/agentguard/time-range';

export function TimeRangeSelect() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const current = searchParams.get('timeRange') ?? '';

  const onChange = useCallback(
    (value: string) => {
      const params = new URLSearchParams(searchParams.toString());
      if (value) {
        params.set('timeRange', value);
      } else {
        params.delete('timeRange');
      }
      params.delete('page');
      router.push(`${pathname}?${params.toString()}`);
    },
    [router, pathname, searchParams],
  );

  return (
    <select
      value={current}
      onChange={(e) => onChange(e.target.value)}
      className="border-input bg-background text-foreground rounded-md border px-3 py-1.5 text-sm"
    >
      <option value="">All Time</option>
      {TIME_RANGE_OPTIONS.map((t) => (
        <option key={t.value} value={t.value}>
          {t.label}
        </option>
      ))}
    </select>
  );
}
```

**Step 2: Commit**

```bash
git add apps/web/components/time-range-select.tsx
git commit -m "feat: add shared TimeRangeSelect component"
```

---

### Task 3: Homepage Loaders + Page + Charts

**Files:**
- Modify: `apps/web/app/home/[account]/_lib/server/homepage.loader.ts`
- Modify: `apps/web/app/home/[account]/page.tsx`
- Modify: `apps/web/app/home/[account]/_components/homepage-charts.tsx`

**Step 1: Update homepage.loader.ts**

Add import at top:
```typescript
import { TIME_RANGE_INTERVALS, type TimeRange } from '~/lib/agentguard/time-range';
```

Update 6 functions to accept `timeRange?: TimeRange` and use dynamic interval:

- `loadHomepageKpis(orgId: string, timeRange?: TimeRange)` — replace `INTERVAL '24 hours'` with `INTERVAL '${TIME_RANGE_INTERVALS[timeRange ?? '24h']}'`
- `loadAgentHealth(orgId: string, timeRange?: TimeRange)` — same, default `'24h'`
- `loadAlertSummary(orgId: string, timeRange?: TimeRange)` — same, default `'24h'`
- `loadHomepageTrend(orgId: string, timeRange?: TimeRange)` — same, default `'24h'`
- `loadFailurePatterns(orgId: string, timeRange?: TimeRange)` — same, default `'7d'`
- `loadAnomalyAlerts(orgId: string, timeRange?: TimeRange)` — same, default `'7d'`

Do NOT change `loadRecentActivity` or `loadPlanUsage`.

**Step 2: Update page.tsx**

Add `searchParams` to props interface:
```typescript
interface TeamAccountHomePageProps {
  params: Promise<{ account: string }>;
  searchParams: Promise<{ timeRange?: string }>;
}
```

Add import:
```typescript
import { parseTimeRange } from '~/lib/agentguard/time-range';
```

In the async function, await searchParams and pass timeRange to loaders:
```typescript
const { timeRange: rawTimeRange } = await searchParams;
const timeRange = parseTimeRange(rawTimeRange);
// ...
loadHomepageKpis(orgId, timeRange),
loadAgentHealth(orgId, timeRange),
loadAlertSummary(orgId, timeRange),
loadHomepageTrend(orgId, timeRange),
loadPlanUsage(orgId, account),  // unchanged
loadFailurePatterns(orgId, timeRange),
loadAnomalyAlerts(orgId, timeRange),
```

**Step 3: Update homepage-charts.tsx**

Add import:
```typescript
import { TimeRangeSelect } from '~/components/time-range-select';
```

Add `<TimeRangeSelect />` at the top of the return JSX, before the KPI grid:
```tsx
<div className="flex items-center justify-end">
  <TimeRangeSelect />
</div>
```

**Step 4: Verify**

Run: `cd nextjs-application && pnpm typecheck`
Expected: No new errors in web app

**Step 5: Commit**

```bash
git add apps/web/app/home/[account]/_lib/server/homepage.loader.ts \
  apps/web/app/home/[account]/page.tsx \
  apps/web/app/home/[account]/_components/homepage-charts.tsx
git commit -m "feat: add time range selector to homepage"
```

---

### Task 4: Fleet Health Loaders + Page + Charts

**Files:**
- Modify: `apps/web/app/home/[account]/agents/_lib/server/fleet-health.loader.ts`
- Modify: `apps/web/app/home/[account]/agents/page.tsx`
- Modify: `apps/web/app/home/[account]/agents/_components/fleet-health-charts.tsx`

**Step 1: Update fleet-health.loader.ts**

Add import:
```typescript
import { TIME_RANGE_INTERVALS, type TimeRange } from '~/lib/agentguard/time-range';
```

Update 4 functions:
- `loadFleetKpis(orgId: string, timeRange?: TimeRange)` — default `'24h'`
- `loadAgentFleetTable(orgId: string, page = 1, timeRange?: TimeRange)` — default `'24h'`
- `loadExecutionsOverTime(orgId: string, timeRange?: TimeRange)` — default `'7d'`. Only change the `INTERVAL '7 days'` on the materialized CTE (line 153). Keep `INTERVAL '10 minutes'` realtime patch hardcoded (line 165).
- `loadFleetRecentSessions(orgId: string, timeRange?: TimeRange)` — default `'7d'`

**Step 2: Update agents/page.tsx**

Expand `searchParams` interface:
```typescript
searchParams: Promise<{ page?: string; timeRange?: string }>;
```

Add import:
```typescript
import { parseTimeRange } from '~/lib/agentguard/time-range';
```

Parse and pass:
```typescript
const timeRange = parseTimeRange(filters.timeRange);
// ...
loadFleetKpis(orgId, timeRange),
loadAgentFleetTable(orgId, page, timeRange),
loadExecutionsOverTime(orgId, timeRange),
loadFleetRecentSessions(orgId, timeRange),
```

**Step 3: Update fleet-health-charts.tsx**

Add import:
```typescript
import { TimeRangeSelect } from '~/components/time-range-select';
```

Add `<TimeRangeSelect />` at top of return JSX before the KPI grid.

**Step 4: Verify**

Run: `cd nextjs-application && pnpm typecheck`

**Step 5: Commit**

```bash
git add apps/web/app/home/[account]/agents/_lib/server/fleet-health.loader.ts \
  apps/web/app/home/[account]/agents/page.tsx \
  apps/web/app/home/[account]/agents/_components/fleet-health-charts.tsx
git commit -m "feat: add time range selector to agents fleet page"
```

---

### Task 5: Agent Detail Loaders + Page + Charts

**Files:**
- Modify: `apps/web/app/home/[account]/agents/[agentId]/_lib/server/agent-detail.loader.ts`
- Modify: `apps/web/app/home/[account]/agents/[agentId]/page.tsx`
- Modify: `apps/web/app/home/[account]/agents/[agentId]/_components/agent-detail-charts.tsx`

**Step 1: Update agent-detail.loader.ts**

Add import:
```typescript
import { TIME_RANGE_INTERVALS, type TimeRange } from '~/lib/agentguard/time-range';
```

Update 7 functions:
- `loadAgentKpis(agentId: string, timeRange?: TimeRange)` — default `'24h'`
- `loadAgentConfidenceOverTime(agentId: string, timeRange?: TimeRange)` — default `'7d'`
- `loadAgentActionDistribution(agentId: string, timeRange?: TimeRange)` — default `'24h'`
- `loadCheckScoreTrends(agentId: string, timeRange?: TimeRange)` — default `'7d'`
- `loadCorrectionStats(agentId: string, timeRange?: TimeRange)` — default `'30d'`
- `loadCorrectionLayerUsage(agentId: string, timeRange?: TimeRange)` — default `'30d'`
- `loadAgentAnomalyAlerts(agentId: string, timeRange?: TimeRange)` — default `'7d'`

Do NOT change `loadAgent`, `loadRecentExecutions`, or `loadRecentSessions`.

**Step 2: Update agents/[agentId]/page.tsx**

Add `searchParams` to props:
```typescript
interface AgentDetailPageProps {
  params: Promise<{ account: string; agentId: string }>;
  searchParams: Promise<{ timeRange?: string }>;
}
```

Add import:
```typescript
import { parseTimeRange } from '~/lib/agentguard/time-range';
```

Parse and pass:
```typescript
async function AgentDetailPage({ params, searchParams }: AgentDetailPageProps) {
  const { account, agentId } = await params;
  const { timeRange: rawTimeRange } = await searchParams;
  const timeRange = parseTimeRange(rawTimeRange);
  // ...
  loadAgentKpis(agentId, timeRange),
  loadAgentConfidenceOverTime(agentId, timeRange),
  loadAgentActionDistribution(agentId, timeRange),
  loadRecentExecutions(agentId),  // unchanged
  loadCheckScoreTrends(agentId, timeRange),
  loadCorrectionStats(agentId, timeRange),
  loadCorrectionLayerUsage(agentId, timeRange),
  loadAgentAnomalyAlerts(agentId, timeRange),
```

**Step 3: Update agent-detail-charts.tsx**

Add import:
```typescript
import { TimeRangeSelect } from '~/components/time-range-select';
```

Add `<TimeRangeSelect />` at top of return JSX before the KPI grid.

**Step 4: Verify**

Run: `cd nextjs-application && pnpm typecheck`

**Step 5: Commit**

```bash
git add apps/web/app/home/[account]/agents/[agentId]/_lib/server/agent-detail.loader.ts \
  apps/web/app/home/[account]/agents/[agentId]/page.tsx \
  apps/web/app/home/[account]/agents/[agentId]/_components/agent-detail-charts.tsx
git commit -m "feat: add time range selector to agent detail page"
```

---

### Task 6: Tools Loaders + Page + Charts

**Files:**
- Modify: `apps/web/app/home/[account]/tools/_lib/server/tool-usage.loader.ts`
- Modify: `apps/web/app/home/[account]/tools/page.tsx`
- Modify: `apps/web/app/home/[account]/tools/_components/tool-usage-charts.tsx`

**Step 1: Update tool-usage.loader.ts**

Add import:
```typescript
import { TIME_RANGE_INTERVALS, type TimeRange } from '~/lib/agentguard/time-range';
```

Update all 5 functions:
- `loadToolUsage(orgId: string, timeRange?: TimeRange)` — default `'7d'`
- `loadToolUsageKpis(orgId: string, timeRange?: TimeRange)` — default `'7d'`
- `loadToolUsageTimeSeries(orgId: string, timeRange?: TimeRange)` — default `'7d'`
- `loadToolRiskMatrix(orgId: string, timeRange?: TimeRange)` — default `'7d'`
- `loadToolAnomalies(orgId: string, timeRange?: TimeRange)` — default `'7d'`. Only change the outer `INTERVAL '7 days'` filter. The internal today/avg7 CTE partition logic stays as-is.

**Step 2: Update tools/page.tsx**

Add `searchParams` to props:
```typescript
interface ToolUsagePageProps {
  params: Promise<{ account: string }>;
  searchParams: Promise<{ timeRange?: string }>;
}
```

Add import:
```typescript
import { parseTimeRange } from '~/lib/agentguard/time-range';
```

Parse and pass:
```typescript
async function ToolUsagePage({ params, searchParams }: ToolUsagePageProps) {
  const { account } = await params;
  const { timeRange: rawTimeRange } = await searchParams;
  const timeRange = parseTimeRange(rawTimeRange);
  const orgId = await resolveOrgId(account);

  const [tools, kpis, timeSeries, riskMatrix, anomalies] = await Promise.all([
    loadToolUsage(orgId, timeRange),
    loadToolUsageKpis(orgId, timeRange),
    loadToolUsageTimeSeries(orgId, timeRange),
    loadToolRiskMatrix(orgId, timeRange),
    loadToolAnomalies(orgId, timeRange),
  ]);
```

**Step 3: Update tool-usage-charts.tsx**

Add import:
```typescript
import { TimeRangeSelect } from '~/components/time-range-select';
```

Add `<TimeRangeSelect />` at top of return JSX before the KPI grid.

**Step 4: Verify**

Run: `cd nextjs-application && pnpm typecheck`

**Step 5: Commit**

```bash
git add apps/web/app/home/[account]/tools/_lib/server/tool-usage.loader.ts \
  apps/web/app/home/[account]/tools/page.tsx \
  apps/web/app/home/[account]/tools/_components/tool-usage-charts.tsx
git commit -m "feat: add time range selector to tools page"
```

---

### Task 7: Final Verification

**Step 1: Full typecheck**

Run: `cd nextjs-application && pnpm typecheck`
Expected: No new errors in web app (only pre-existing admin/landing errors)

**Step 2: Lint and format**

Run: `cd nextjs-application && pnpm lint:fix && pnpm format:fix`

**Step 3: Commit any formatting changes**

```bash
git add -A && git commit -m "chore: lint and format"
```
