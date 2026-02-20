# Time Range Selector — Design

## Goal

Add a time range selector to the 4 dashboard pages that currently have hardcoded time windows (homepage, agents fleet, agent detail, tools). Users should be able to switch between 1h, 24h, 7d, and 30d views.

## What Already Exists

- `alerts/`, `sessions/`, `failures/` pages already have time range selectors via URL search params (`?timeRange=24h`)
- Pattern: `TIME_RANGE_INTERVALS` map, `Filters` interface with `timeRange` field, `useSearchParams` + `useRouter` in client component, `<select>` UI
- Each of the 3 pages duplicates the constants and select UI locally

## What's Hardcoded Today

| Page | Loader Functions | Hardcoded Intervals |
|---|---|---|
| Homepage | 6 functions | 4x `'24 hours'`, 2x `'7 days'` |
| Agents Fleet | 4 functions | 2x `'24 hours'`, 2x `'7 days'` |
| Agent Detail | 7 functions | 2x `'24 hours'`, 3x `'7 days'`, 2x `'30 days'` |
| Tools | 5 functions | 5x `'7 days'` |

Not changed: `loadRecentActivity` (LIMIT-only), `loadPlanUsage` (billing), `loadRecentExecutions`, `loadRecentSessions` (LIMIT-only).

## Approach

### Shared Utility (`lib/agentguard/time-range.ts`)

Single source of truth for:
- `TimeRange` type: `'1h' | '24h' | '7d' | '30d'`
- `TIME_RANGE_INTERVALS`: maps to SQL interval strings
- `TIME_RANGE_OPTIONS`: display labels for select UI
- `parseTimeRange()`: safe cast from URL string

### Shared Component (`components/time-range-select.tsx`)

Client component using `useSearchParams` + `useRouter` + `usePathname`. Renders a `<select>` with the 4 options. Resets `page` param on change. Reads current value from URL — no props needed from server.

### Loader Changes

Every affected loader gets an optional `timeRange?: TimeRange` parameter. Default matches the current hardcoded value. SQL interpolates `TIME_RANGE_INTERVALS[timeRange ?? default]` instead of a literal.

### Page Changes

Each page reads `searchParams.timeRange`, calls `parseTimeRange()`, passes to all loaders in `Promise.all`.

### Client Component Changes

Each charts component imports and renders `<TimeRangeSelect />` above the KPI grid.

## Special Cases

- `loadExecutionsOverTime`: The 10-minute realtime patch (TimescaleDB continuous aggregate supplement) stays hardcoded — it's infrastructure, not a user filter.
- `loadToolAnomalies`: Only the outer time filter changes; the internal today/avg7 CTE partition logic stays as-is.

## Non-Goals

- Migrating the existing 3 pages (alerts, sessions, failures) to the shared utility — separate cleanup PR
- Custom date range picker — YAGNI
- Persisting time range preference — URL params are sufficient
