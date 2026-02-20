# Tool Usage Analytics Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform the Tool Usage page from a raw data table into an actionable 4-section dashboard with KPI cards, visual charts (stacked area + heatmap), anomaly detection cards, enriched table, and tool_policy guardrail enforcement.

**Architecture:** New materialized view `tool_usage_daily` for time-series data. Anomaly detection computed server-side in loaders comparing current vs 7-day averages. Tool policies implemented as a new `tool_policy` rule type in the existing guardrails system, enforced in the verification pipeline by inspecting execution steps. Dashboard uses the established dynamic-import pattern (dashboard shim → charts component).

**Tech Stack:** Next.js 16 (App Router), React 19, TypeScript, Recharts via `@kit/ui/chart`, PostgreSQL materialized views, Alembic migrations, Python verification engine.

---

### Task 1: Migration — `tool_usage_daily` Materialized View

**Files:**
- Create: `services/migrations/alembic/versions/013_add_tool_usage_daily.py`

**Step 1: Create the migration file**

```python
"""Add tool_usage_daily materialized view for tool analytics dashboard.

Aggregates tool call data into daily buckets per org/tool/agent for
time-series charts, anomaly detection, and risk heatmap.

Revision ID: 013
Revises: 012
Create Date: 2026-02-20
"""

from typing import Sequence, Union

from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE MATERIALIZED VIEW tool_usage_daily AS
        SELECT
            date_trunc('day', tc.timestamp) AS bucket,
            tc.org_id,
            tc.tool_name,
            tc.agent_id,
            COUNT(*) AS call_count,
            AVG(tc.duration_ms) AS avg_duration_ms,
            AVG(CASE WHEN e.action = 'flag' THEN 1.0 ELSE 0.0 END) AS flag_rate,
            AVG(CASE WHEN e.action = 'block' THEN 1.0 ELSE 0.0 END) AS block_rate
        FROM tool_calls tc
        JOIN executions e ON tc.execution_id = e.execution_id
        GROUP BY bucket, tc.org_id, tc.tool_name, tc.agent_id
        WITH NO DATA;
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX ix_tool_usage_daily_bucket_org_tool_agent
        ON tool_usage_daily (bucket, org_id, tool_name, agent_id);
        """
    )

    op.execute(
        """
        CREATE INDEX ix_tool_usage_daily_org_bucket
        ON tool_usage_daily (org_id, bucket);
        """
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS tool_usage_daily CASCADE")
```

**Step 2: Run migration on Neon**

```bash
cd services/migrations
DATABASE_URL='<neon_connection_string>' .venv/bin/alembic upgrade head
```

Expected: `012 -> 013`

**Step 3: Refresh the materialized view**

```bash
DATABASE_URL='<neon_connection_string>' .venv/bin/python -c "
import os, psycopg2
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute('REFRESH MATERIALIZED VIEW tool_usage_daily')
conn.commit()
cur.execute('SELECT count(*) FROM tool_usage_daily')
print('tool_usage_daily rows:', cur.fetchone()[0])
conn.close()
"
```

Expected: Non-zero row count.

**Step 4: Commit**

```bash
git add services/migrations/alembic/versions/013_add_tool_usage_daily.py
git commit -m "feat: add tool_usage_daily materialized view for analytics dashboard"
```

---

### Task 2: TypeScript Types & Loaders

**Files:**
- Modify: `apps/web/lib/agentguard/types.ts` (add new interfaces after line 364)
- Modify: `apps/web/app/home/[account]/tools/_lib/server/tool-usage.loader.ts` (add 4 new loaders)

**Step 1: Add new TypeScript types**

Add after the existing `ToolUsageRow` interface in `apps/web/lib/agentguard/types.ts`:

```typescript
/**
 * KPI aggregates for the tool usage dashboard.
 */
export interface ToolUsageKpis {
  total_calls: number;
  unique_tools: number;
  anomaly_count: number;
  active_policies: number;
}

/**
 * Daily time-series bucket for tool call volume chart.
 */
export interface ToolCallDailyBucket {
  bucket: string;
  tool_name: string;
  call_count: number;
}

/**
 * Tool × agent risk matrix cell for heatmap.
 */
export interface ToolRiskCell {
  tool_name: string;
  agent_id: string;
  call_count: number;
  block_rate: number;
}

/**
 * Detected anomaly for a tool.
 */
export interface ToolAnomaly {
  severity: 'critical' | 'high' | 'medium';
  tool_name: string;
  agent_id: string | null;
  anomaly_type: string;
  description: string;
  current_value: number;
  baseline_value: number;
}
```

**Step 2: Add new loaders**

Replace the contents of `apps/web/app/home/[account]/tools/_lib/server/tool-usage.loader.ts` with:

```typescript
import 'server-only';

import { cache } from 'react';

import { getAgentGuardPool } from '~/lib/agentguard/db';
import type {
  ToolAnomaly,
  ToolCallDailyBucket,
  ToolRiskCell,
  ToolUsageKpis,
  ToolUsageRow,
} from '~/lib/agentguard/types';

/**
 * Load tool usage analytics for an org (last 7 days).
 */
export const loadToolUsage = cache(
  async (orgId: string): Promise<ToolUsageRow[]> => {
    try {
      const pool = getAgentGuardPool();

      const result = await pool.query<{
        tool_name: string;
        call_count: string;
        avg_duration_ms: number | null;
        agents_using: string;
        flag_rate: number | null;
        block_rate: number | null;
      }>(
        `
        SELECT
          tc.tool_name,
          COUNT(*) AS call_count,
          AVG(tc.duration_ms) AS avg_duration_ms,
          COUNT(DISTINCT tc.agent_id) AS agents_using,
          AVG(CASE WHEN e.action = 'flag' THEN 1.0 ELSE 0.0 END) AS flag_rate,
          AVG(CASE WHEN e.action = 'block' THEN 1.0 ELSE 0.0 END) AS block_rate
        FROM tool_calls tc
        JOIN executions e ON tc.execution_id = e.execution_id
        WHERE tc.org_id = $1
          AND tc.timestamp >= NOW() - INTERVAL '7 days'
        GROUP BY tc.tool_name
        ORDER BY call_count DESC
        LIMIT 50
        `,
        [orgId],
      );

      return result.rows.map((row) => ({
        tool_name: row.tool_name,
        call_count: parseInt(row.call_count, 10),
        avg_duration_ms: row.avg_duration_ms,
        agents_using: parseInt(row.agents_using, 10),
        flag_rate: row.flag_rate,
        block_rate: row.block_rate,
      }));
    } catch {
      return [];
    }
  },
);

/**
 * Load KPI aggregates for the tool usage dashboard.
 */
export const loadToolUsageKpis = cache(
  async (orgId: string): Promise<ToolUsageKpis> => {
    try {
      const pool = getAgentGuardPool();

      const result = await pool.query<{
        total_calls: string;
        unique_tools: string;
      }>(
        `
        SELECT
          COUNT(*) AS total_calls,
          COUNT(DISTINCT tool_name) AS unique_tools
        FROM tool_calls
        WHERE org_id = $1
          AND timestamp >= NOW() - INTERVAL '7 days'
        `,
        [orgId],
      );

      const policyResult = await pool.query<{ count: string }>(
        `
        SELECT COUNT(*) AS count
        FROM guardrails
        WHERE org_id = $1
          AND rule_type = 'tool_policy'
          AND enabled = true
        `,
        [orgId],
      );

      const row = result.rows[0];

      return {
        total_calls: parseInt(row?.total_calls ?? '0', 10),
        unique_tools: parseInt(row?.unique_tools ?? '0', 10),
        anomaly_count: 0, // computed after anomalies are loaded
        active_policies: parseInt(policyResult.rows[0]?.count ?? '0', 10),
      };
    } catch {
      return { total_calls: 0, unique_tools: 0, anomaly_count: 0, active_policies: 0 };
    }
  },
);

/**
 * Load daily time-series for the stacked area chart (7 days).
 */
export const loadToolUsageTimeSeries = cache(
  async (orgId: string): Promise<ToolCallDailyBucket[]> => {
    try {
      const pool = getAgentGuardPool();

      const result = await pool.query<{
        bucket: string;
        tool_name: string;
        call_count: string;
      }>(
        `
        SELECT
          bucket,
          tool_name,
          SUM(call_count)::text AS call_count
        FROM tool_usage_daily
        WHERE org_id = $1
          AND bucket >= NOW() - INTERVAL '7 days'
        GROUP BY bucket, tool_name
        ORDER BY bucket ASC, tool_name ASC
        `,
        [orgId],
      );

      return result.rows.map((row) => ({
        bucket: row.bucket,
        tool_name: row.tool_name,
        call_count: parseInt(row.call_count, 10),
      }));
    } catch {
      return [];
    }
  },
);

/**
 * Load tool × agent risk matrix for heatmap (7 days).
 */
export const loadToolRiskMatrix = cache(
  async (orgId: string): Promise<ToolRiskCell[]> => {
    try {
      const pool = getAgentGuardPool();

      const result = await pool.query<{
        tool_name: string;
        agent_id: string;
        call_count: string;
        block_rate: number | null;
      }>(
        `
        SELECT
          tool_name,
          agent_id,
          SUM(call_count)::text AS call_count,
          AVG(block_rate) AS block_rate
        FROM tool_usage_daily
        WHERE org_id = $1
          AND bucket >= NOW() - INTERVAL '7 days'
        GROUP BY tool_name, agent_id
        ORDER BY tool_name, agent_id
        `,
        [orgId],
      );

      return result.rows.map((row) => ({
        tool_name: row.tool_name,
        agent_id: row.agent_id,
        call_count: parseInt(row.call_count, 10),
        block_rate: row.block_rate ?? 0,
      }));
    } catch {
      return [];
    }
  },
);

/**
 * Detect tool usage anomalies by comparing current vs 7-day averages.
 */
export const loadToolAnomalies = cache(
  async (orgId: string): Promise<ToolAnomaly[]> => {
    try {
      const pool = getAgentGuardPool();

      const result = await pool.query<{
        tool_name: string;
        agent_id: string;
        today_count: string;
        avg_7d_count: string;
        today_block_rate: number | null;
        today_avg_duration: number | null;
        avg_7d_duration: number | null;
      }>(
        `
        WITH daily AS (
          SELECT
            tool_name,
            agent_id,
            bucket,
            SUM(call_count) AS call_count,
            AVG(avg_duration_ms) AS avg_duration_ms,
            AVG(block_rate) AS block_rate
          FROM tool_usage_daily
          WHERE org_id = $1
            AND bucket >= NOW() - INTERVAL '7 days'
          GROUP BY tool_name, agent_id, bucket
        ),
        today AS (
          SELECT
            tool_name,
            agent_id,
            SUM(call_count) AS today_count,
            AVG(block_rate) AS today_block_rate,
            AVG(avg_duration_ms) AS today_avg_duration
          FROM daily
          WHERE bucket >= date_trunc('day', NOW())
          GROUP BY tool_name, agent_id
        ),
        avg7 AS (
          SELECT
            tool_name,
            agent_id,
            AVG(call_count) AS avg_7d_count,
            AVG(avg_duration_ms) AS avg_7d_duration
          FROM daily
          WHERE bucket < date_trunc('day', NOW())
          GROUP BY tool_name, agent_id
        )
        SELECT
          t.tool_name,
          t.agent_id,
          t.today_count::text,
          COALESCE(a.avg_7d_count, 0)::text AS avg_7d_count,
          t.today_block_rate,
          t.today_avg_duration,
          a.avg_7d_duration
        FROM today t
        LEFT JOIN avg7 a ON t.tool_name = a.tool_name AND t.agent_id = a.agent_id
        `,
        [orgId],
      );

      const anomalies: ToolAnomaly[] = [];

      for (const row of result.rows) {
        const todayCount = parseInt(row.today_count, 10);
        const avg7dCount = parseFloat(row.avg_7d_count);
        const blockRate = row.today_block_rate ?? 0;
        const todayDuration = row.today_avg_duration;
        const avg7dDuration = row.avg_7d_duration;

        if (avg7dCount > 0 && todayCount > 2 * avg7dCount) {
          anomalies.push({
            severity: 'medium',
            tool_name: row.tool_name,
            agent_id: row.agent_id,
            anomaly_type: 'volume_spike',
            description: `${row.tool_name} called ${todayCount}x today by ${row.agent_id} (avg: ${Math.round(avg7dCount)}/day)`,
            current_value: todayCount,
            baseline_value: avg7dCount,
          });
        }

        if (blockRate > 0.20) {
          anomalies.push({
            severity: 'high',
            tool_name: row.tool_name,
            agent_id: row.agent_id,
            anomaly_type: 'high_block_rate',
            description: `${row.tool_name} block rate ${(blockRate * 100).toFixed(0)}% for ${row.agent_id}`,
            current_value: blockRate,
            baseline_value: 0.20,
          });
        }

        if (
          todayDuration != null &&
          avg7dDuration != null &&
          avg7dDuration > 0 &&
          todayDuration > 3 * avg7dDuration
        ) {
          anomalies.push({
            severity: 'medium',
            tool_name: row.tool_name,
            agent_id: row.agent_id,
            anomaly_type: 'latency_spike',
            description: `${row.tool_name} avg ${Math.round(todayDuration)}ms today for ${row.agent_id} (avg: ${Math.round(avg7dDuration)}ms)`,
            current_value: todayDuration,
            baseline_value: avg7dDuration,
          });
        }
      }

      // Sort by severity: critical > high > medium
      const severityOrder = { critical: 0, high: 1, medium: 2 };
      anomalies.sort((a, b) => severityOrder[a.severity] - severityOrder[b.severity]);

      return anomalies;
    } catch {
      return [];
    }
  },
);
```

**Step 3: Run typecheck**

```bash
cd nextjs-application && pnpm typecheck
```

Expected: No new errors from the types/loaders.

**Step 4: Commit**

```bash
git add apps/web/lib/agentguard/types.ts apps/web/app/home/\\[account\\]/tools/_lib/server/tool-usage.loader.ts
git commit -m "feat: add tool usage KPI, time-series, risk matrix, and anomaly loaders"
```

---

### Task 3: Translation Keys

**Files:**
- Modify: `apps/web/public/locales/en/agentguard.json` (extend `tools` section)

**Step 1: Add new translation keys**

Add these keys to the existing `"tools"` section in `agentguard.json`:

```json
"tools": {
  "pageTitle": "Tool Usage",
  "pageDescription": "Analytics for tools used by your AI agents",
  "toolName": "Tool Name",
  "callCount": "Calls",
  "avgDuration": "Avg Duration",
  "agentsUsing": "Agents Using",
  "flagRate": "Flag Rate",
  "blockRate": "Block Rate",
  "noTools": "No tool usage data yet. Tool calls are extracted from agent step traces.",
  "totalCalls": "Total Calls",
  "totalCallsSubtitle": "in the last 7 days",
  "uniqueTools": "Unique Tools",
  "uniqueToolsSubtitle": "distinct tools observed",
  "anomaliesDetected": "Anomalies",
  "anomaliesDetectedSubtitle": "detected in last 24 hours",
  "activePolicies": "Tool Policies",
  "activePoliciesSubtitle": "active guardrails",
  "callsOverTime": "Call Volume Over Time",
  "callsOverTimeDescription": "Daily call volume per tool (last 7 days)",
  "riskHeatmap": "Tool Risk Heatmap",
  "riskHeatmapDescription": "Block rate by tool × agent (last 7 days)",
  "anomalies": "Anomalies Detected",
  "anomaliesDescription": "Unusual tool behavior patterns in the last 24 hours",
  "noAnomalies": "No anomalies detected — all tools operating normally.",
  "createGuardrail": "Create Guardrail",
  "anomalyVolume": "Volume Spike",
  "anomalyBlockRate": "High Block Rate",
  "anomalyLatency": "Latency Spike",
  "anomalyToolLoop": "Tool Loop",
  "actions": "Actions",
  "viewExecutions": "View Executions"
}
```

Also add to the `"guardrails"` section:

```json
"ruleTypeToolPolicy": "Tool Policy",
"toolNameLabel": "Tool Name",
"toolNamePlaceholder": "e.g., send_email, web_search",
"policyLabel": "Policy",
"policyDeny": "Deny (block this tool)",
"policyAllow": "Allow with limit",
"maxCallsLabel": "Max Calls Per Execution",
"maxCallsPlaceholder": "e.g., 10"
```

**Step 2: Commit**

```bash
git add apps/web/public/locales/en/agentguard.json
git commit -m "feat: add tool usage dashboard translation keys"
```

---

### Task 4: Dashboard Components — KPIs, Charts, Anomaly Cards

**Files:**
- Create: `apps/web/app/home/[account]/tools/_components/tool-usage-dashboard.tsx`
- Create: `apps/web/app/home/[account]/tools/_components/tool-usage-charts.tsx`

**Step 1: Create the dynamic import shim**

Create `apps/web/app/home/[account]/tools/_components/tool-usage-dashboard.tsx`:

```tsx
'use client';

import dynamic from 'next/dynamic';

import { LoadingOverlay } from '@kit/ui/loading-overlay';

export const ToolUsageDashboard = dynamic(
  () => import('./tool-usage-charts'),
  {
    ssr: false,
    loading: () => (
      <LoadingOverlay
        fullPage={false}
        className={'flex flex-1 flex-col items-center justify-center'}
      />
    ),
  },
);
```

**Step 2: Create the charts component**

Create `apps/web/app/home/[account]/tools/_components/tool-usage-charts.tsx`:

```tsx
'use client';

import { format } from 'date-fns';
import {
  AlertTriangle,
  BarChart3,
  Shield,
  TrendingUp,
  Wrench,
} from 'lucide-react';
import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from 'recharts';

import { Badge } from '@kit/ui/badge';
import { Button } from '@kit/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@kit/ui/card';
import {
  ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from '@kit/ui/chart';
import { Trans } from '@kit/ui/trans';

import type {
  ToolAnomaly,
  ToolCallDailyBucket,
  ToolRiskCell,
  ToolUsageKpis,
  ToolUsageRow,
} from '~/lib/agentguard/types';

import { ToolUsageTable } from './tool-usage-table';

const TOOL_COLORS = [
  '#34C78E', '#F87171', '#60A5FA', '#FBBF24', '#A78BFA',
  '#F472B6', '#34D399', '#FB923C', '#818CF8', '#2DD4BF',
];

interface ToolUsageChartsProps {
  tools: ToolUsageRow[];
  kpis: ToolUsageKpis;
  timeSeries: ToolCallDailyBucket[];
  riskMatrix: ToolRiskCell[];
  anomalies: ToolAnomaly[];
  accountSlug: string;
}

export default function ToolUsageCharts({
  tools,
  kpis,
  timeSeries,
  riskMatrix,
  anomalies,
  accountSlug,
}: ToolUsageChartsProps) {
  // Build stacked area chart data: group by bucket, each tool as a column
  const toolNames = [...new Set(timeSeries.map((r) => r.tool_name))].slice(0, 10);
  const bucketMap = new Map<string, Record<string, number>>();

  for (const row of timeSeries) {
    const key = row.bucket;
    if (!bucketMap.has(key)) {
      bucketMap.set(key, {});
    }
    bucketMap.get(key)![row.tool_name] = (bucketMap.get(key)![row.tool_name] ?? 0) + row.call_count;
  }

  const areaData = Array.from(bucketMap.entries())
    .map(([bucket, counts]) => ({
      bucket: format(new Date(bucket), 'MMM d'),
      ...counts,
    }))
    .sort((a, b) => a.bucket.localeCompare(b.bucket));

  const areaChartConfig = Object.fromEntries(
    toolNames.map((name, i) => [
      name,
      { label: name, color: TOOL_COLORS[i % TOOL_COLORS.length]! },
    ]),
  ) satisfies ChartConfig;

  // Build heatmap data: unique tools × unique agents
  const heatmapTools = [...new Set(riskMatrix.map((r) => r.tool_name))];
  const heatmapAgents = [...new Set(riskMatrix.map((r) => r.agent_id))];
  const riskLookup = new Map(
    riskMatrix.map((r) => [`${r.tool_name}::${r.agent_id}`, r]),
  );

  // Override KPI anomaly count with actual loaded anomalies
  const kpisWithAnomalies = { ...kpis, anomaly_count: anomalies.length };

  return (
    <div className="animate-in fade-in flex flex-col space-y-4 pb-36 duration-500">
      {/* KPI Cards */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          titleKey="agentguard:tools.totalCalls"
          subtitleKey="agentguard:tools.totalCallsSubtitle"
          value={kpisWithAnomalies.total_calls.toLocaleString()}
          icon={<BarChart3 className="h-5 w-5 text-[#8C8C8C]" />}
        />
        <KpiCard
          titleKey="agentguard:tools.uniqueTools"
          subtitleKey="agentguard:tools.uniqueToolsSubtitle"
          value={kpisWithAnomalies.unique_tools.toLocaleString()}
          icon={<Wrench className="h-5 w-5 text-[#8C8C8C]" />}
        />
        <KpiCard
          titleKey="agentguard:tools.anomaliesDetected"
          subtitleKey="agentguard:tools.anomaliesDetectedSubtitle"
          value={kpisWithAnomalies.anomaly_count.toLocaleString()}
          icon={<AlertTriangle className={`h-5 w-5 ${kpisWithAnomalies.anomaly_count > 0 ? 'text-[#F97316]' : 'text-[#8C8C8C]'}`} />}
        />
        <KpiCard
          titleKey="agentguard:tools.activePolicies"
          subtitleKey="agentguard:tools.activePoliciesSubtitle"
          value={kpisWithAnomalies.active_policies.toLocaleString()}
          icon={<Shield className="h-5 w-5 text-[#8C8C8C]" />}
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Stacked Area Chart — Call Volume Over Time */}
        {areaData.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>
                <Trans i18nKey="agentguard:tools.callsOverTime" />
              </CardTitle>
              <CardDescription>
                <Trans i18nKey="agentguard:tools.callsOverTimeDescription" />
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ChartContainer className="h-64 w-full" config={areaChartConfig}>
                <AreaChart accessibilityLayer data={areaData}>
                  <CartesianGrid vertical={false} />
                  <XAxis
                    dataKey="bucket"
                    tickLine={false}
                    axisLine={false}
                    tickMargin={8}
                  />
                  <YAxis
                    tickLine={false}
                    axisLine={false}
                    tickMargin={8}
                    allowDecimals={false}
                  />
                  <ChartTooltip
                    content={<ChartTooltipContent indicator="dot" />}
                  />
                  {toolNames.map((name) => (
                    <Area
                      key={name}
                      dataKey={name}
                      type="natural"
                      fill={`var(--color-${name})`}
                      stroke={`var(--color-${name})`}
                      fillOpacity={0.3}
                      stackId="a"
                    />
                  ))}
                </AreaChart>
              </ChartContainer>
            </CardContent>
          </Card>
        )}

        {/* Risk Heatmap */}
        {heatmapTools.length > 0 && heatmapAgents.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>
                <Trans i18nKey="agentguard:tools.riskHeatmap" />
              </CardTitle>
              <CardDescription>
                <Trans i18nKey="agentguard:tools.riskHeatmapDescription" />
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <div className="inline-block min-w-full">
                  {/* Header row: agent names */}
                  <div className="flex">
                    <div className="w-28 shrink-0" />
                    {heatmapAgents.slice(0, 10).map((agent) => (
                      <div
                        key={agent}
                        className="w-16 shrink-0 truncate px-1 text-center text-[10px] text-muted-foreground"
                        title={agent}
                      >
                        {agent.length > 8
                          ? agent.slice(0, 7) + '…'
                          : agent}
                      </div>
                    ))}
                  </div>
                  {/* Rows: one per tool */}
                  {heatmapTools.slice(0, 10).map((tool) => (
                    <div key={tool} className="flex items-center">
                      <div
                        className="w-28 shrink-0 truncate pr-2 text-right font-mono text-xs text-muted-foreground"
                        title={tool}
                      >
                        {tool}
                      </div>
                      {heatmapAgents.slice(0, 10).map((agent) => {
                        const cell = riskLookup.get(
                          `${tool}::${agent}`,
                        );
                        const rate = cell?.block_rate ?? 0;
                        const bg =
                          !cell
                            ? 'bg-muted/20'
                            : rate > 0.3
                              ? 'bg-[#F87171]/60'
                              : rate > 0.1
                                ? 'bg-[#FBBF24]/40'
                                : rate > 0
                                  ? 'bg-[#FBBF24]/20'
                                  : 'bg-[#34C78E]/30';
                        return (
                          <div
                            key={`${tool}::${agent}`}
                            className={`m-[1px] h-8 w-16 shrink-0 rounded-sm ${bg} flex items-center justify-center text-[10px] text-muted-foreground`}
                            title={`${tool} × ${agent}: ${cell ? `${(rate * 100).toFixed(0)}% block rate, ${cell.call_count} calls` : 'no data'}`}
                          >
                            {cell
                              ? `${(rate * 100).toFixed(0)}%`
                              : ''}
                          </div>
                        );
                      })}
                    </div>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Anomalies Section */}
      <Card>
        <CardHeader>
          <CardTitle>
            <Trans i18nKey="agentguard:tools.anomalies" />
          </CardTitle>
          <CardDescription>
            <Trans i18nKey="agentguard:tools.anomaliesDescription" />
          </CardDescription>
        </CardHeader>
        <CardContent>
          {anomalies.length === 0 ? (
            <p className="text-muted-foreground py-4 text-center text-sm">
              <Trans i18nKey="agentguard:tools.noAnomalies" />
            </p>
          ) : (
            <div className="space-y-3">
              {anomalies.map((anomaly, idx) => (
                <AnomalyCard
                  key={`${anomaly.tool_name}-${anomaly.anomaly_type}-${idx}`}
                  anomaly={anomaly}
                  accountSlug={accountSlug}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Enriched Table */}
      <Card>
        <CardHeader>
          <CardTitle>
            <Trans i18nKey="agentguard:tools.pageDescription" />
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ToolUsageTable tools={tools} anomalies={anomalies} />
        </CardContent>
      </Card>
    </div>
  );
}

function KpiCard({
  titleKey,
  subtitleKey,
  value,
  icon,
}: {
  titleKey: string;
  subtitleKey: string;
  value: string;
  icon: React.ReactNode;
}) {
  return (
    <Card className="border-border bg-card">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <span className="text-base font-medium text-[#F0F0F0]">
          <Trans i18nKey={titleKey} />
        </span>
        {icon}
      </CardHeader>
      <CardContent>
        <div className="text-sm text-[#8C8C8C]">
          <Trans i18nKey={subtitleKey} />
        </div>
        <div className="mt-3 text-4xl font-semibold text-[#F0F0F0]">
          {value}
        </div>
      </CardContent>
    </Card>
  );
}

function AnomalyCard({
  anomaly,
  accountSlug,
}: {
  anomaly: ToolAnomaly;
  accountSlug: string;
}) {
  const severityStyles = {
    critical:
      'border-[#F87171]/30 bg-[#F87171]/5',
    high: 'border-[#F97316]/30 bg-[#F97316]/5',
    medium:
      'border-[#FBBF24]/30 bg-[#FBBF24]/5',
  };

  const severityBadgeStyles = {
    critical: 'bg-[#F87171]/15 text-[#F87171] border-[#F87171]/30',
    high: 'bg-[#F97316]/15 text-[#F97316] border-[#F97316]/30',
    medium: 'bg-[#FBBF24]/15 text-[#FBBF24] border-[#FBBF24]/30',
  };

  return (
    <div
      className={`flex items-center justify-between rounded-lg border p-3 ${severityStyles[anomaly.severity]}`}
    >
      <div className="flex items-center gap-3">
        <Badge
          variant="outline"
          className={severityBadgeStyles[anomaly.severity]}
        >
          {anomaly.severity}
        </Badge>
        <div>
          <p className="text-sm font-medium text-[#F0F0F0]">
            {anomaly.description}
          </p>
          {anomaly.agent_id && (
            <a
              href={`/home/${accountSlug}/agents/${anomaly.agent_id}`}
              className="text-xs text-[#8C8C8C] hover:underline"
            >
              {anomaly.agent_id}
            </a>
          )}
        </div>
      </div>
      <a
        href={`/home/${accountSlug}/settings/guardrails?prefill_tool=${anomaly.tool_name}&prefill_agent=${anomaly.agent_id ?? ''}`}
      >
        <Button variant="outline" size="sm">
          <Shield className="mr-1 h-3 w-3" />
          <Trans i18nKey="agentguard:tools.createGuardrail" />
        </Button>
      </a>
    </div>
  );
}
```

**Step 3: Run typecheck**

```bash
cd nextjs-application && pnpm typecheck
```

Expected: No new errors. The `ToolUsageTable` props will need updating in the next task.

**Step 4: Commit**

```bash
git add apps/web/app/home/\\[account\\]/tools/_components/tool-usage-dashboard.tsx apps/web/app/home/\\[account\\]/tools/_components/tool-usage-charts.tsx
git commit -m "feat: add tool usage dashboard with KPIs, charts, heatmap, and anomaly cards"
```

---

### Task 5: Update Table with Anomaly Indicators & Page Integration

**Files:**
- Modify: `apps/web/app/home/[account]/tools/_components/tool-usage-table.tsx`
- Modify: `apps/web/app/home/[account]/tools/page.tsx`

**Step 1: Update the table to accept anomalies prop and show indicators**

In `tool-usage-table.tsx`, update the interface and add an anomaly indicator column:

- Add `anomalies?: ToolAnomaly[]` to `ToolUsageTableProps`
- Add import for `ToolAnomaly` from types
- Add `AlertTriangle` icon import from lucide-react
- Add a new column header "Status" before "Actions"
- In each row, check if `anomalies.some(a => a.tool_name === tool.tool_name)` and show `<AlertTriangle className="h-4 w-4 text-[#F97316]" />` if true, otherwise a green check or dash

**Step 2: Update page.tsx to use the new dashboard**

Replace `apps/web/app/home/[account]/tools/page.tsx` with:

```tsx
import { AppBreadcrumbs } from '@kit/ui/app-breadcrumbs';
import { PageBody } from '@kit/ui/page';
import { Trans } from '@kit/ui/trans';

import { resolveOrgId } from '~/lib/agentguard/resolve-org-id';
import { createI18nServerInstance } from '~/lib/i18n/i18n.server';
import { withI18n } from '~/lib/i18n/with-i18n';

import { TeamAccountLayoutPageHeader } from '../_components/team-account-layout-page-header';
import { ToolUsageDashboard } from './_components/tool-usage-dashboard';
import {
  loadToolAnomalies,
  loadToolRiskMatrix,
  loadToolUsage,
  loadToolUsageKpis,
  loadToolUsageTimeSeries,
} from './_lib/server/tool-usage.loader';

interface ToolUsagePageProps {
  params: Promise<{ account: string }>;
}

export const generateMetadata = async () => {
  const i18n = await createI18nServerInstance();
  const title = i18n.t('agentguard:tools.pageTitle');

  return {
    title,
  };
};

async function ToolUsagePage({ params }: ToolUsagePageProps) {
  const { account } = await params;
  const orgId = await resolveOrgId(account);

  const [tools, kpis, timeSeries, riskMatrix, anomalies] = await Promise.all([
    loadToolUsage(orgId),
    loadToolUsageKpis(orgId),
    loadToolUsageTimeSeries(orgId),
    loadToolRiskMatrix(orgId),
    loadToolAnomalies(orgId),
  ]);

  return (
    <>
      <TeamAccountLayoutPageHeader
        account={account}
        title={<Trans i18nKey="agentguard:tools.pageTitle" />}
        description={<AppBreadcrumbs />}
      />

      <PageBody>
        <ToolUsageDashboard
          tools={tools}
          kpis={kpis}
          timeSeries={timeSeries}
          riskMatrix={riskMatrix}
          anomalies={anomalies}
          accountSlug={account}
        />
      </PageBody>
    </>
  );
}

export default withI18n(ToolUsagePage);
```

**Step 3: Run typecheck**

```bash
cd nextjs-application && pnpm typecheck
```

Expected: Pass (may need to fix ToolUsageTable anomalies prop).

**Step 4: Visual verification**

Navigate to `http://localhost:3000/home/test/tools` and verify:
- 4 KPI cards at top (Total Calls, Unique Tools, Anomalies, Tool Policies)
- Stacked area chart showing call volume over time
- Risk heatmap showing tool × agent block rates
- Anomaly cards (if any detected)
- Enriched table at the bottom

**Step 5: Commit**

```bash
git add apps/web/app/home/\\[account\\]/tools/_components/tool-usage-table.tsx apps/web/app/home/\\[account\\]/tools/page.tsx
git commit -m "feat: integrate tool usage dashboard into page with all loaders"
```

---

### Task 6: Tool Policy Guardrail — Schema & Frontend

**Files:**
- Modify: `apps/web/app/home/[account]/settings/guardrails/_lib/schema/guardrail.schema.ts` (add `tool_policy` to RULE_TYPES)
- Modify: `apps/web/app/home/[account]/settings/guardrails/_components/create-guardrail-dialog.tsx` (add tool_policy form fields)

**Step 1: Update Zod schema**

In `guardrail.schema.ts`, change line 3:

```typescript
const RULE_TYPES = ['regex', 'keyword', 'threshold', 'llm', 'tool_policy'] as const;
```

**Step 2: Update create dialog with tool_policy form fields**

In `create-guardrail-dialog.tsx`:

- Add `RuleType` union to include `'tool_policy'`
- Add state for tool_policy condition: `toolName`, `policy` (deny/allow), `maxCalls`
- Add `buildCondition()` case for `tool_policy`:
  ```typescript
  case 'tool_policy':
    return policy === 'deny'
      ? { tool_name: toolName, policy: 'deny' }
      : { tool_name: toolName, policy: 'allow', max_calls_per_execution: parseInt(maxCalls, 10) };
  ```
- Add `isFormValid()` case:
  ```typescript
  case 'tool_policy':
    return toolName.trim().length > 0 && (policy === 'deny' || (maxCalls.trim().length > 0 && !isNaN(parseInt(maxCalls, 10))));
  ```
- Add `resetForm()` entries for the new state variables
- Add `SelectItem` for `tool_policy` in the rule type dropdown
- Add condition UI for `tool_policy`:
  ```tsx
  {ruleType === 'tool_policy' && (
    <div className="space-y-3">
      <Input value={toolName} onChange={(e) => setToolName(e.target.value)}
             placeholder="e.g., send_email, web_search" />
      <Select value={policy} onValueChange={setPolicy}>
        <SelectTrigger><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value="deny">Deny (block this tool)</SelectItem>
          <SelectItem value="allow">Allow with limit</SelectItem>
        </SelectContent>
      </Select>
      {policy === 'allow' && (
        <Input type="number" value={maxCalls} onChange={(e) => setMaxCalls(e.target.value)}
               placeholder="Max calls per execution (e.g., 10)" />
      )}
    </div>
  )}
  ```

- Support URL prefill: read `searchParams` or use `useSearchParams` to auto-populate `toolName` and `agentId` when navigating from the anomaly card "Create Guardrail" link.

**Step 3: Run typecheck**

```bash
cd nextjs-application && pnpm typecheck
```

**Step 4: Visual verification**

Navigate to `/home/test/settings/guardrails`, click Create Guardrail, select "Tool Policy" rule type. Verify:
- Tool name input appears
- Policy selector (Deny / Allow with limit)
- Max calls field appears when "Allow with limit" is selected

**Step 5: Commit**

```bash
git add apps/web/app/home/\\[account\\]/settings/guardrails/_lib/schema/guardrail.schema.ts apps/web/app/home/\\[account\\]/settings/guardrails/_components/create-guardrail-dialog.tsx
git commit -m "feat: add tool_policy rule type to guardrails schema and create dialog"
```

---

### Task 7: Tool Policy Guardrail — Backend Enforcement

**Files:**
- Modify: `services/verification-engine/engine/guardrails.py` (add `_eval_tool_policy` and wire into dispatch)
- Modify: `services/verification-engine/engine/pipeline.py` (pass `steps` to guardrails check)
- Modify: `services/verification-engine/engine/models.py` (add `steps` param to guardrails check signature if needed)
- Create: `services/verification-engine/tests/test_tool_policy.py`

**Step 1: Write the failing test**

Create `services/verification-engine/tests/test_tool_policy.py`:

```python
"""Tests for tool_policy guardrail rule type."""

import pytest

from engine.guardrails import check
from engine.models import GuardrailRule, StepRecord


@pytest.mark.asyncio
async def test_tool_policy_deny_blocks_matching_tool():
    """A deny policy should trigger when the denied tool appears in steps."""
    rules = [
        GuardrailRule(
            name="Block send_email",
            rule_type="tool_policy",
            condition={"tool_name": "send_email", "policy": "deny"},
            action="block",
        ),
    ]
    steps = [
        StepRecord(step_type="tool_call", name="web_search"),
        StepRecord(step_type="tool_call", name="send_email"),
    ]
    result = await check(output="some output", rules=rules, steps=steps)
    assert not result.passed
    assert result.score == 0.0
    violations = result.details.get("violations", [])
    assert len(violations) == 1
    assert violations[0]["rule_name"] == "Block send_email"


@pytest.mark.asyncio
async def test_tool_policy_deny_passes_when_tool_not_used():
    """A deny policy should not trigger when the denied tool is absent."""
    rules = [
        GuardrailRule(
            name="Block send_email",
            rule_type="tool_policy",
            condition={"tool_name": "send_email", "policy": "deny"},
            action="block",
        ),
    ]
    steps = [
        StepRecord(step_type="tool_call", name="web_search"),
        StepRecord(step_type="tool_call", name="calculator"),
    ]
    result = await check(output="some output", rules=rules, steps=steps)
    assert result.passed
    assert result.score == 1.0


@pytest.mark.asyncio
async def test_tool_policy_allow_with_limit_blocks_excess():
    """An allow-with-limit policy should trigger when call count exceeds limit."""
    rules = [
        GuardrailRule(
            name="Limit web_search",
            rule_type="tool_policy",
            condition={"tool_name": "web_search", "policy": "allow", "max_calls_per_execution": 3},
            action="flag",
        ),
    ]
    steps = [
        StepRecord(step_type="tool_call", name="web_search"),
        StepRecord(step_type="tool_call", name="web_search"),
        StepRecord(step_type="tool_call", name="web_search"),
        StepRecord(step_type="tool_call", name="web_search"),  # 4th call
    ]
    result = await check(output="some output", rules=rules, steps=steps)
    assert not result.passed
    violations = result.details.get("violations", [])
    assert len(violations) == 1


@pytest.mark.asyncio
async def test_tool_policy_allow_within_limit_passes():
    """An allow-with-limit policy should pass when count is within limit."""
    rules = [
        GuardrailRule(
            name="Limit web_search",
            rule_type="tool_policy",
            condition={"tool_name": "web_search", "policy": "allow", "max_calls_per_execution": 5},
            action="flag",
        ),
    ]
    steps = [
        StepRecord(step_type="tool_call", name="web_search"),
        StepRecord(step_type="tool_call", name="web_search"),
    ]
    result = await check(output="some output", rules=rules, steps=steps)
    assert result.passed


@pytest.mark.asyncio
async def test_tool_policy_no_steps_passes():
    """When no steps are provided, tool_policy rules should not trigger."""
    rules = [
        GuardrailRule(
            name="Block send_email",
            rule_type="tool_policy",
            condition={"tool_name": "send_email", "policy": "deny"},
            action="block",
        ),
    ]
    result = await check(output="some output", rules=rules, steps=None)
    assert result.passed
```

**Step 2: Run tests to verify they fail**

```bash
cd services/verification-engine
python -m pytest tests/test_tool_policy.py -v
```

Expected: FAIL (check function doesn't accept `steps` param yet).

**Step 3: Implement `_eval_tool_policy` in guardrails.py**

Add after the `_eval_llm` function:

```python
def _eval_tool_policy(
    condition: Dict[str, Any],
    steps: Optional[List] = None,
) -> Dict[str, Any]:
    """Evaluate a tool_policy rule against execution steps.

    Condition format:
    - {"tool_name": "send_email", "policy": "deny"} — deny this tool
    - {"tool_name": "web_search", "policy": "allow", "max_calls_per_execution": 10}
    """
    tool_name = condition.get("tool_name", "")
    policy = condition.get("policy", "deny")

    if not steps or not tool_name:
        return {"violated": False, "reason": "no steps or tool_name"}

    tool_calls = [
        s for s in steps
        if getattr(s, "step_type", None) == "tool_call"
        and getattr(s, "name", None) == tool_name
    ]

    if policy == "deny":
        if tool_calls:
            return {
                "violated": True,
                "tool_name": tool_name,
                "call_count": len(tool_calls),
                "reason": f"Tool '{tool_name}' is denied by policy",
            }
        return {"violated": False}

    if policy == "allow":
        max_calls = condition.get("max_calls_per_execution")
        if max_calls is not None and len(tool_calls) > int(max_calls):
            return {
                "violated": True,
                "tool_name": tool_name,
                "call_count": len(tool_calls),
                "max_allowed": int(max_calls),
                "reason": f"Tool '{tool_name}' called {len(tool_calls)} times, max {max_calls}",
            }
        return {"violated": False}

    return {"violated": False, "reason": f"unknown policy '{policy}'"}
```

**Step 4: Update `check()` function signature to accept `steps`**

Change line 151:
```python
async def check(
    output: Any,
    rules: List[GuardrailRule],
    metadata: Optional[Dict[str, Any]] = None,
    steps: Optional[List] = None,
) -> CheckResult:
```

Add to the dispatch block (after line 198):
```python
        elif rule.rule_type == "tool_policy":
            result = _eval_tool_policy(rule.condition, steps)
```

**Step 5: Update pipeline.py to pass steps to guardrails check**

In `pipeline.py` line 138, change:
```python
llm_tasks.append(guardrails_checker.check(output, cfg.guardrails, metadata))
```
to:
```python
llm_tasks.append(guardrails_checker.check(output, cfg.guardrails, metadata, steps=steps))
```

**Step 6: Run tests**

```bash
cd services/verification-engine
python -m pytest tests/test_tool_policy.py -v
python -m pytest tests/test_guardrails.py -v
python -m pytest tests/test_pipeline.py -v
```

Expected: All pass.

**Step 7: Commit**

```bash
git add services/verification-engine/engine/guardrails.py services/verification-engine/engine/pipeline.py services/verification-engine/tests/test_tool_policy.py
git commit -m "feat: add tool_policy guardrail enforcement in verification pipeline"
```

---

### Task 8: Guardrails Table Display for Tool Policy

**Files:**
- Modify: `apps/web/app/home/[account]/settings/guardrails/_components/guardrails-table.tsx`

**Step 1: Update the table to display tool_policy rules nicely**

The guardrails table already shows `rule_type` as a badge. Ensure `tool_policy` renders with a distinct label. In the rule type badge rendering, add a mapping:

```tsx
const ruleTypeLabels: Record<string, string> = {
  regex: 'Regex',
  keyword: 'Keyword',
  threshold: 'Threshold',
  llm: 'LLM',
  tool_policy: 'Tool Policy',
};
```

For the "Scope" column, if `rule_type === 'tool_policy'`, show the tool name from `condition.tool_name` instead of just "All Agents".

**Step 2: Run typecheck and visual verification**

```bash
cd nextjs-application && pnpm typecheck
```

Navigate to `/home/test/settings/guardrails`, create a tool_policy guardrail, verify it displays correctly.

**Step 3: Commit**

```bash
git add apps/web/app/home/\\[account\\]/settings/guardrails/_components/guardrails-table.tsx
git commit -m "feat: display tool_policy guardrails with tool name in table"
```

---

### Task 9: Final Verification & Cleanup

**Step 1: Run full typecheck**

```bash
cd nextjs-application && pnpm typecheck
```

**Step 2: Run lint and format**

```bash
cd nextjs-application && pnpm lint:fix && pnpm format:fix
```

**Step 3: Run verification engine tests**

```bash
cd services/verification-engine
python -m pytest tests/ -v
```

**Step 4: Visual end-to-end verification**

1. Navigate to `/home/test/tools` — verify all 4 sections render
2. Navigate to `/home/test/settings/guardrails` — create a tool_policy guardrail
3. Verify the guardrail appears in the table with "Tool Policy" badge
4. Go back to `/home/test/tools` — verify "Active Policies" KPI increments

**Step 5: Commit any remaining fixes**

```bash
git add -A && git commit -m "chore: lint and format tool usage dashboard"
```
