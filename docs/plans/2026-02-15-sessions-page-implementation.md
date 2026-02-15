# Sessions Page Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a dedicated Sessions page to the Vex dashboard with a session-centric list view (filters: agent, date, status) and a session detail page showing turn-by-turn timeline.

**Architecture:** Two new routes — `/home/[account]/sessions` (filtered list grouped by session) and `/home/[account]/sessions/[sessionId]` (detail with turn timeline). Data derived from `executions` table via `GROUP BY session_id`. Follows existing page patterns (server component + dynamic client dashboard).

**Tech Stack:** Next.js 16 App Router, React 19, `@kit/ui` components (Card, Badge, Table, Tabs), PostgreSQL via `getAgentGuardPool()`, React `cache()` for loaders, `date-fns` for formatting.

---

### Task 1: Types, Paths, Navigation, and i18n

**Files:**
- Modify: `apps/web/lib/agentguard/types.ts`
- Modify: `apps/web/config/paths.config.ts`
- Modify: `apps/web/config/team-account-navigation.config.tsx`
- Modify: `apps/web/public/locales/en/agentguard.json`

**Step 1: Add types to `types.ts`**

Add these interfaces at the end of the file (before the closing of file):

```typescript
/**
 * A session row for the sessions list page.
 */
export interface SessionListRow {
  session_id: string;
  agent_id: string;
  agent_name: string;
  turn_count: number;
  avg_confidence: number | null;
  first_timestamp: string;
  last_timestamp: string;
  has_block: boolean;
  has_flag: boolean;
}

/**
 * A single turn (execution) in a session detail view.
 */
export interface SessionTurn {
  execution_id: string;
  sequence_number: number | null;
  task: string | null;
  confidence: number | null;
  action: 'pass' | 'flag' | 'block';
  latency_ms: number | null;
  timestamp: string;
  corrected: boolean;
  token_count: number | null;
  cost_estimate: number | null;
  metadata: Record<string, unknown>;
}

/**
 * Session detail header aggregates.
 */
export interface SessionDetailHeader {
  session_id: string;
  agent_id: string;
  agent_name: string;
  turn_count: number;
  avg_confidence: number | null;
  first_timestamp: string;
  last_timestamp: string;
  total_tokens: number | null;
  total_cost: number | null;
}
```

**Step 2: Add paths to `paths.config.ts`**

Add to the `PathsSchema` `app` object:
```typescript
accountSessions: z.string().min(1),
accountSessionDetail: z.string().min(1),
```

Add to the `pathsConfig.app` object:
```typescript
accountSessions: '/home/[account]/sessions',
accountSessionDetail: '/home/[account]/sessions/[sessionId]',
```

**Step 3: Add Sessions to navigation**

In `team-account-navigation.config.tsx`:

Add `MessageSquare` to the lucide-react import:
```typescript
import {
  AlertTriangle,
  Bot,
  CreditCard,
  Key,
  LayoutDashboard,
  MessageSquare,
  Settings,
  ShieldAlert,
  Users,
} from 'lucide-react';
```

Add Sessions item to the Monitoring section children array, after the Agents entry:
```typescript
{
  label: 'agentguard:nav.sessions',
  path: createPath(pathsConfig.app.accountSessions, account),
  Icon: <MessageSquare className={iconClasses} />,
},
```

**Step 4: Add i18n keys**

Add to `agentguard.json` — add `"sessions"` key to `"nav"`:
```json
"sessions": "Sessions"
```

Add new top-level `"sessions"` section:
```json
"sessions": {
  "pageTitle": "Sessions",
  "pageDescription": "Multi-turn conversation sessions across all agents",
  "filters": "Filters",
  "agent": "Agent",
  "status": "Status",
  "timeRange": "Time Range",
  "allAgents": "All Agents",
  "allStatuses": "All Statuses",
  "allTime": "All Time",
  "last24h": "Last 24 hours",
  "last7d": "Last 7 days",
  "last30d": "Last 30 days",
  "statusHealthy": "Healthy",
  "statusDegraded": "Degraded",
  "statusRisky": "Risky",
  "sessionId": "Session",
  "turns": "Turns",
  "avgConfidence": "Avg Confidence",
  "duration": "Duration",
  "lastActive": "Last Active",
  "noSessions": "No sessions found.",
  "detailTitle": "Session Detail",
  "detailDescription": "Turn-by-turn timeline for this session",
  "totalTokens": "Total Tokens",
  "totalCost": "Total Cost",
  "turnTimeline": "Turn Timeline",
  "turn": "Turn {{number}}",
  "task": "Task",
  "confidence": "Confidence",
  "action": "Action",
  "latency": "Latency",
  "timestamp": "Timestamp",
  "corrected": "Corrected",
  "sessionNotFound": "Session not found."
}
```

**Step 5: Commit**

```bash
git add apps/web/lib/agentguard/types.ts apps/web/config/paths.config.ts apps/web/config/team-account-navigation.config.tsx apps/web/public/locales/en/agentguard.json
git commit -m "feat(sessions): add types, paths, nav, and i18n for sessions page"
```

---

### Task 2: Sessions List Loader

**Files:**
- Create: `apps/web/app/home/[account]/sessions/_lib/server/sessions.loader.ts`

**Step 1: Create the loader**

```typescript
import 'server-only';

import { cache } from 'react';

import { getAgentGuardPool } from '~/lib/agentguard/db';
import type { SessionDetailHeader, SessionListRow, SessionTurn } from '~/lib/agentguard/types';

export interface SessionFilters {
  agentId?: string;
  status?: 'healthy' | 'degraded' | 'risky';
  timeRange?: '24h' | '7d' | '30d';
}

const TIME_RANGE_INTERVALS: Record<string, string> = {
  '24h': '24 hours',
  '7d': '7 days',
  '30d': '30 days',
};

/**
 * Load paginated session list for an organization with optional filters.
 */
export const loadSessionList = cache(
  async (orgId: string, filters?: SessionFilters): Promise<SessionListRow[]> => {
    const pool = getAgentGuardPool();

    const conditions: string[] = ['e.org_id = $1', 'e.session_id IS NOT NULL'];
    const params: unknown[] = [orgId];
    let paramIndex = 2;

    if (filters?.agentId) {
      conditions.push(`e.agent_id = $${paramIndex}`);
      params.push(filters.agentId);
      paramIndex++;
    }

    if (filters?.timeRange) {
      const interval = TIME_RANGE_INTERVALS[filters.timeRange];

      if (interval) {
        conditions.push(`e.timestamp >= NOW() - INTERVAL '${interval}'`);
      }
    }

    const whereClause = conditions.join(' AND ');

    // Status filter is applied post-aggregation via HAVING or wrapping query
    let statusFilter = '';

    if (filters?.status === 'risky') {
      statusFilter = 'HAVING BOOL_OR(e.action = \'block\') = TRUE';
    } else if (filters?.status === 'degraded') {
      statusFilter =
        'HAVING BOOL_OR(e.action = \'block\') = FALSE AND BOOL_OR(e.action = \'flag\') = TRUE';
    } else if (filters?.status === 'healthy') {
      statusFilter =
        'HAVING BOOL_OR(e.action = \'block\') = FALSE AND BOOL_OR(e.action = \'flag\') = FALSE';
    }

    const result = await pool.query<{
      session_id: string;
      agent_id: string;
      agent_name: string;
      turn_count: string;
      avg_confidence: number | null;
      first_timestamp: string;
      last_timestamp: string;
      has_block: boolean;
      has_flag: boolean;
    }>(
      `
      SELECT
        e.session_id,
        e.agent_id,
        a.name AS agent_name,
        COUNT(*) AS turn_count,
        AVG(e.confidence) AS avg_confidence,
        MIN(e.timestamp) AS first_timestamp,
        MAX(e.timestamp) AS last_timestamp,
        BOOL_OR(e.action = 'block') AS has_block,
        BOOL_OR(e.action = 'flag') AS has_flag
      FROM executions e
      JOIN agents a ON e.agent_id = a.agent_id AND e.org_id = a.org_id
      WHERE ${whereClause}
      GROUP BY e.session_id, e.agent_id, a.name
      ${statusFilter}
      ORDER BY MAX(e.timestamp) DESC
      LIMIT 50
      `,
      params,
    );

    return result.rows.map((row) => ({
      session_id: row.session_id,
      agent_id: row.agent_id,
      agent_name: row.agent_name,
      turn_count: parseInt(row.turn_count, 10),
      avg_confidence: row.avg_confidence,
      first_timestamp: row.first_timestamp,
      last_timestamp: row.last_timestamp,
      has_block: row.has_block,
      has_flag: row.has_flag,
    }));
  },
);

/**
 * Load session detail header (aggregates).
 */
export const loadSessionDetail = cache(
  async (
    sessionId: string,
    orgId: string,
  ): Promise<SessionDetailHeader | null> => {
    const pool = getAgentGuardPool();

    const result = await pool.query<{
      session_id: string;
      agent_id: string;
      agent_name: string;
      turn_count: string;
      avg_confidence: number | null;
      first_timestamp: string;
      last_timestamp: string;
      total_tokens: string | null;
      total_cost: number | null;
    }>(
      `
      SELECT
        e.session_id,
        e.agent_id,
        a.name AS agent_name,
        COUNT(*) AS turn_count,
        AVG(e.confidence) AS avg_confidence,
        MIN(e.timestamp) AS first_timestamp,
        MAX(e.timestamp) AS last_timestamp,
        SUM(e.token_count) AS total_tokens,
        SUM(e.cost_estimate) AS total_cost
      FROM executions e
      JOIN agents a ON e.agent_id = a.agent_id AND e.org_id = a.org_id
      WHERE e.session_id = $1 AND e.org_id = $2
      GROUP BY e.session_id, e.agent_id, a.name
      `,
      [sessionId, orgId],
    );

    if (result.rows.length === 0) return null;

    const row = result.rows[0]!;

    return {
      session_id: row.session_id,
      agent_id: row.agent_id,
      agent_name: row.agent_name,
      turn_count: parseInt(row.turn_count, 10),
      avg_confidence: row.avg_confidence,
      first_timestamp: row.first_timestamp,
      last_timestamp: row.last_timestamp,
      total_tokens: row.total_tokens ? parseInt(row.total_tokens, 10) : null,
      total_cost: row.total_cost,
    };
  },
);

/**
 * Load all turns (executions) for a session, ordered by sequence.
 */
export const loadSessionTurns = cache(
  async (sessionId: string, orgId: string): Promise<SessionTurn[]> => {
    const pool = getAgentGuardPool();

    const result = await pool.query<SessionTurn>(
      `
      SELECT
        e.execution_id,
        e.sequence_number,
        e.task,
        e.confidence,
        e.action,
        e.latency_ms,
        e.timestamp,
        e.corrected,
        e.token_count,
        e.cost_estimate,
        e.metadata
      FROM executions e
      WHERE e.session_id = $1 AND e.org_id = $2
      ORDER BY e.sequence_number ASC, e.timestamp ASC
      `,
      [sessionId, orgId],
    );

    return result.rows;
  },
);
```

**Step 2: Verify typecheck passes**

Run: `cd nextjs-application && pnpm typecheck`
Expected: PASS

**Step 3: Commit**

```bash
git add apps/web/app/home/[account]/sessions/_lib/server/sessions.loader.ts
git commit -m "feat(sessions): add session list and detail data loaders"
```

---

### Task 3: Sessions List Page and Dashboard Component

**Files:**
- Create: `apps/web/app/home/[account]/sessions/page.tsx`
- Create: `apps/web/app/home/[account]/sessions/_components/sessions-dashboard.tsx`
- Create: `apps/web/app/home/[account]/sessions/_components/sessions-table.tsx`

**Step 1: Create the server page component**

`apps/web/app/home/[account]/sessions/page.tsx`:

```typescript
import { AppBreadcrumbs } from '@kit/ui/app-breadcrumbs';
import { PageBody } from '@kit/ui/page';
import { Trans } from '@kit/ui/trans';

import { getAgentGuardPool } from '~/lib/agentguard/db';
import { resolveOrgId } from '~/lib/agentguard/resolve-org-id';
import { createI18nServerInstance } from '~/lib/i18n/i18n.server';
import { withI18n } from '~/lib/i18n/with-i18n';

import { TeamAccountLayoutPageHeader } from '../_components/team-account-layout-page-header';
import { SessionsDashboard } from './_components/sessions-dashboard';
import { loadSessionList } from './_lib/server/sessions.loader';

interface SessionsPageProps {
  params: Promise<{ account: string }>;
  searchParams: Promise<{
    agent?: string;
    status?: string;
    timeRange?: string;
  }>;
}

export const generateMetadata = async () => {
  const i18n = await createI18nServerInstance();
  const title = i18n.t('agentguard:sessions.pageTitle');

  return {
    title,
  };
};

async function SessionsPage({ params, searchParams }: SessionsPageProps) {
  const { account } = await params;
  const filters = await searchParams;
  const orgId = await resolveOrgId(account);

  const [sessions, agentsResult] = await Promise.all([
    loadSessionList(orgId, {
      agentId: filters.agent,
      status: filters.status as 'healthy' | 'degraded' | 'risky' | undefined,
      timeRange: filters.timeRange as '24h' | '7d' | '30d' | undefined,
    }),
    getAgentGuardPool().query<{ agent_id: string; name: string }>(
      'SELECT agent_id, name FROM agents WHERE org_id = $1 ORDER BY name',
      [orgId],
    ),
  ]);

  return (
    <>
      <TeamAccountLayoutPageHeader
        account={account}
        title={<Trans i18nKey={'agentguard:sessions.pageTitle'} />}
        description={<AppBreadcrumbs />}
      />

      <PageBody>
        <SessionsDashboard
          sessions={sessions}
          accountSlug={account}
          agents={agentsResult.rows}
        />
      </PageBody>
    </>
  );
}

export default withI18n(SessionsPage);
```

**Step 2: Create the dynamic dashboard wrapper**

`apps/web/app/home/[account]/sessions/_components/sessions-dashboard.tsx`:

```typescript
'use client';

import dynamic from 'next/dynamic';

import { LoadingOverlay } from '@kit/ui/loading-overlay';

export const SessionsDashboard = dynamic(() => import('./sessions-table'), {
  ssr: false,
  loading: () => (
    <LoadingOverlay
      fullPage={false}
      className={'flex flex-1 flex-col items-center justify-center'}
    />
  ),
});
```

**Step 3: Create the sessions table with filters**

`apps/web/app/home/[account]/sessions/_components/sessions-table.tsx`:

```typescript
'use client';

import { useCallback } from 'react';

import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';

import { formatDistanceStrict } from 'date-fns';

import { Badge } from '@kit/ui/badge';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@kit/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@kit/ui/table';
import { Trans } from '@kit/ui/trans';

import {
  formatConfidence,
  formatTimestamp,
  truncateId,
} from '~/lib/agentguard/formatters';
import type { SessionListRow } from '~/lib/agentguard/types';

interface SessionsTableProps {
  sessions: SessionListRow[];
  accountSlug: string;
  agents: Array<{ agent_id: string; name: string }>;
}

const STATUS_OPTIONS = [
  { value: 'healthy', labelKey: 'agentguard:sessions.statusHealthy' },
  { value: 'degraded', labelKey: 'agentguard:sessions.statusDegraded' },
  { value: 'risky', labelKey: 'agentguard:sessions.statusRisky' },
];

const TIME_RANGE_OPTIONS = [
  { value: '24h', labelKey: 'agentguard:sessions.last24h' },
  { value: '7d', labelKey: 'agentguard:sessions.last7d' },
  { value: '30d', labelKey: 'agentguard:sessions.last30d' },
];

function getSessionStatus(
  row: SessionListRow,
): 'healthy' | 'degraded' | 'risky' {
  if (row.has_block) return 'risky';
  if (row.has_flag) return 'degraded';
  return 'healthy';
}

function StatusBadge({ status }: { status: 'healthy' | 'degraded' | 'risky' }) {
  const styles: Record<string, string> = {
    healthy:
      'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
    degraded:
      'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200',
    risky: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  };

  return (
    <Badge variant="outline" className={styles[status]}>
      <Trans i18nKey={`agentguard:sessions.status${status.charAt(0).toUpperCase() + status.slice(1)}`} />
    </Badge>
  );
}

function formatDuration(start: string, end: string): string {
  const startDate = new Date(start);
  const endDate = new Date(end);
  const diffMs = endDate.getTime() - startDate.getTime();

  if (diffMs < 1000) return '<1s';

  return formatDistanceStrict(startDate, endDate);
}

export default function SessionsTable({
  sessions,
  accountSlug,
  agents,
}: SessionsTableProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const currentAgent = searchParams.get('agent') ?? '';
  const currentStatus = searchParams.get('status') ?? '';
  const currentTimeRange = searchParams.get('timeRange') ?? '';

  const updateFilter = useCallback(
    (key: string, value: string) => {
      const params = new URLSearchParams(searchParams.toString());

      if (value) {
        params.set(key, value);
      } else {
        params.delete(key);
      }

      router.push(`${pathname}?${params.toString()}`);
    },
    [router, pathname, searchParams],
  );

  return (
    <div
      className={
        'animate-in fade-in flex flex-col space-y-4 pb-36 duration-500'
      }
    >
      {/* Filter Bar */}
      <Card>
        <CardHeader>
          <CardTitle>
            <Trans i18nKey="agentguard:sessions.filters" />
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-4">
            {/* Agent Filter */}
            <div className="flex flex-col gap-1">
              <label className="text-muted-foreground text-xs">
                <Trans i18nKey="agentguard:sessions.agent" />
              </label>
              <select
                value={currentAgent}
                onChange={(e) => updateFilter('agent', e.target.value)}
                className="border-input bg-background rounded-md border px-3 py-1.5 text-sm"
              >
                <option value="">
                  All Agents
                </option>
                {agents.map((a) => (
                  <option key={a.agent_id} value={a.agent_id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </div>

            {/* Status Filter */}
            <div className="flex flex-col gap-1">
              <label className="text-muted-foreground text-xs">
                <Trans i18nKey="agentguard:sessions.status" />
              </label>
              <select
                value={currentStatus}
                onChange={(e) => updateFilter('status', e.target.value)}
                className="border-input bg-background rounded-md border px-3 py-1.5 text-sm"
              >
                <option value="">
                  All Statuses
                </option>
                {STATUS_OPTIONS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.value.charAt(0).toUpperCase() + s.value.slice(1)}
                  </option>
                ))}
              </select>
            </div>

            {/* Time Range Filter */}
            <div className="flex flex-col gap-1">
              <label className="text-muted-foreground text-xs">
                <Trans i18nKey="agentguard:sessions.timeRange" />
              </label>
              <select
                value={currentTimeRange}
                onChange={(e) => updateFilter('timeRange', e.target.value)}
                className="border-input bg-background rounded-md border px-3 py-1.5 text-sm"
              >
                <option value="">
                  All Time
                </option>
                {TIME_RANGE_OPTIONS.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.value === '24h'
                      ? 'Last 24 hours'
                      : t.value === '7d'
                        ? 'Last 7 days'
                        : 'Last 30 days'}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Sessions Table */}
      <Card>
        <CardHeader>
          <CardTitle>
            <Trans i18nKey="agentguard:sessions.pageTitle" />
          </CardTitle>
          <CardDescription>
            <Trans i18nKey="agentguard:sessions.pageDescription" />
          </CardDescription>
        </CardHeader>
        <CardContent>
          {sessions.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              <Trans i18nKey="agentguard:sessions.noSessions" />
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>
                    <Trans i18nKey="agentguard:sessions.sessionId" />
                  </TableHead>
                  <TableHead>
                    <Trans i18nKey="agentguard:sessions.agent" />
                  </TableHead>
                  <TableHead>
                    <Trans i18nKey="agentguard:sessions.turns" />
                  </TableHead>
                  <TableHead>
                    <Trans i18nKey="agentguard:sessions.avgConfidence" />
                  </TableHead>
                  <TableHead>
                    <Trans i18nKey="agentguard:sessions.status" />
                  </TableHead>
                  <TableHead>
                    <Trans i18nKey="agentguard:sessions.duration" />
                  </TableHead>
                  <TableHead>
                    <Trans i18nKey="agentguard:sessions.lastActive" />
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sessions.map((session) => {
                  const status = getSessionStatus(session);
                  const confidenceValue = session.avg_confidence;
                  let confidenceColor = 'text-muted-foreground';

                  if (confidenceValue != null) {
                    if (confidenceValue >= 0.8) {
                      confidenceColor =
                        'text-green-600 dark:text-green-400';
                    } else if (confidenceValue >= 0.5) {
                      confidenceColor =
                        'text-yellow-600 dark:text-yellow-400';
                    } else {
                      confidenceColor = 'text-red-600 dark:text-red-400';
                    }
                  }

                  return (
                    <TableRow key={session.session_id}>
                      <TableCell>
                        <Link
                          href={`/home/${accountSlug}/sessions/${session.session_id}`}
                          className="text-primary font-mono text-sm hover:underline"
                        >
                          {truncateId(session.session_id)}
                        </Link>
                      </TableCell>
                      <TableCell>
                        <Link
                          href={`/home/${accountSlug}/agents/${session.agent_id}`}
                          className="text-primary hover:underline"
                        >
                          {session.agent_name}
                        </Link>
                      </TableCell>
                      <TableCell>{session.turn_count}</TableCell>
                      <TableCell>
                        <span className={`font-medium ${confidenceColor}`}>
                          {formatConfidence(session.avg_confidence)}
                        </span>
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={status} />
                      </TableCell>
                      <TableCell>
                        {formatDuration(
                          session.first_timestamp,
                          session.last_timestamp,
                        )}
                      </TableCell>
                      <TableCell>
                        {formatTimestamp(session.last_timestamp)}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
```

**Step 4: Verify typecheck passes**

Run: `cd nextjs-application && pnpm typecheck`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/web/app/home/[account]/sessions/
git commit -m "feat(sessions): add sessions list page with filters"
```

---

### Task 4: Session Detail Page

**Files:**
- Create: `apps/web/app/home/[account]/sessions/[sessionId]/page.tsx`
- Create: `apps/web/app/home/[account]/sessions/[sessionId]/_components/session-detail-dashboard.tsx`
- Create: `apps/web/app/home/[account]/sessions/[sessionId]/_components/session-timeline.tsx`

**Step 1: Create the server page component**

`apps/web/app/home/[account]/sessions/[sessionId]/page.tsx`:

```typescript
import { AppBreadcrumbs } from '@kit/ui/app-breadcrumbs';
import { PageBody } from '@kit/ui/page';
import { Trans } from '@kit/ui/trans';

import { resolveOrgId } from '~/lib/agentguard/resolve-org-id';
import { createI18nServerInstance } from '~/lib/i18n/i18n.server';
import { withI18n } from '~/lib/i18n/with-i18n';

import { TeamAccountLayoutPageHeader } from '../../../_components/team-account-layout-page-header';
import { SessionDetailDashboard } from './_components/session-detail-dashboard';
import {
  loadSessionDetail,
  loadSessionTurns,
} from '../../_lib/server/sessions.loader';

interface SessionDetailPageProps {
  params: Promise<{ account: string; sessionId: string }>;
}

export const generateMetadata = async () => {
  const i18n = await createI18nServerInstance();
  const title = i18n.t('agentguard:sessions.detailTitle');

  return {
    title,
  };
};

async function SessionDetailPage({ params }: SessionDetailPageProps) {
  const { account, sessionId } = await params;
  const orgId = await resolveOrgId(account);

  const [header, turns] = await Promise.all([
    loadSessionDetail(sessionId, orgId),
    loadSessionTurns(sessionId, orgId),
  ]);

  if (!header) {
    return (
      <>
        <TeamAccountLayoutPageHeader
          account={account}
          title={<Trans i18nKey={'agentguard:sessions.detailTitle'} />}
          description={<AppBreadcrumbs />}
        />

        <PageBody>
          <p className="text-muted-foreground text-sm">
            <Trans i18nKey="agentguard:sessions.sessionNotFound" />
          </p>
        </PageBody>
      </>
    );
  }

  return (
    <>
      <TeamAccountLayoutPageHeader
        account={account}
        title={<Trans i18nKey={'agentguard:sessions.detailTitle'} />}
        description={<AppBreadcrumbs />}
      />

      <PageBody>
        <SessionDetailDashboard
          header={header}
          turns={turns}
          accountSlug={account}
        />
      </PageBody>
    </>
  );
}

export default withI18n(SessionDetailPage);
```

**Step 2: Create the dynamic dashboard wrapper**

`apps/web/app/home/[account]/sessions/[sessionId]/_components/session-detail-dashboard.tsx`:

```typescript
'use client';

import dynamic from 'next/dynamic';

import { LoadingOverlay } from '@kit/ui/loading-overlay';

export const SessionDetailDashboard = dynamic(
  () => import('./session-timeline'),
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

**Step 3: Create the session timeline component**

`apps/web/app/home/[account]/sessions/[sessionId]/_components/session-timeline.tsx`:

```typescript
'use client';

import Link from 'next/link';

import { formatDistanceStrict } from 'date-fns';
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Clock,
  Wrench,
} from 'lucide-react';

import { Badge } from '@kit/ui/badge';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@kit/ui/card';
import { Trans } from '@kit/ui/trans';

import {
  formatConfidence,
  formatCost,
  formatLatency,
  formatTimestamp,
  formatTokens,
} from '~/lib/agentguard/formatters';
import type { SessionDetailHeader, SessionTurn } from '~/lib/agentguard/types';

interface SessionTimelineProps {
  header: SessionDetailHeader;
  turns: SessionTurn[];
  accountSlug: string;
}

function ActionIcon({ action }: { action: string }) {
  if (action === 'pass') {
    return <CheckCircle2 className="h-5 w-5 text-green-500" />;
  }

  if (action === 'flag') {
    return <AlertTriangle className="h-5 w-5 text-amber-500" />;
  }

  return <XCircle className="h-5 w-5 text-red-500" />;
}

function ActionBadge({ action }: { action: string }) {
  const styles: Record<string, string> = {
    pass: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
    flag: 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200',
    block: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  };

  return (
    <Badge variant="outline" className={styles[action] ?? ''}>
      <Trans i18nKey={`agentguard:common.${action}`} />
    </Badge>
  );
}

export default function SessionTimeline({
  header,
  turns,
  accountSlug,
}: SessionTimelineProps) {
  const duration = formatDistanceStrict(
    new Date(header.first_timestamp),
    new Date(header.last_timestamp),
  );

  return (
    <div
      className={
        'animate-in fade-in flex flex-col space-y-4 pb-36 duration-500'
      }
    >
      {/* Header Stats */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="font-mono text-base">
                {header.session_id}
              </CardTitle>
              <CardDescription>
                <Link
                  href={`/home/${accountSlug}/agents/${header.agent_id}`}
                  className="text-primary hover:underline"
                >
                  {header.agent_name}
                </Link>
                {' · '}
                {duration}
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
            <StatPill
              label={<Trans i18nKey="agentguard:sessions.turns" />}
              value={header.turn_count.toString()}
            />
            <StatPill
              label={<Trans i18nKey="agentguard:sessions.avgConfidence" />}
              value={formatConfidence(header.avg_confidence)}
            />
            <StatPill
              label={<Trans i18nKey="agentguard:sessions.duration" />}
              value={duration}
            />
            <StatPill
              label={<Trans i18nKey="agentguard:sessions.totalTokens" />}
              value={formatTokens(header.total_tokens)}
            />
            <StatPill
              label={<Trans i18nKey="agentguard:sessions.totalCost" />}
              value={formatCost(header.total_cost)}
            />
          </div>
        </CardContent>
      </Card>

      {/* Turn Timeline */}
      <Card>
        <CardHeader>
          <CardTitle>
            <Trans i18nKey="agentguard:sessions.turnTimeline" />
          </CardTitle>
          <CardDescription>
            <Trans i18nKey="agentguard:sessions.detailDescription" />
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="relative space-y-0">
            {turns.map((turn, index) => (
              <div key={turn.execution_id} className="relative flex gap-4">
                {/* Timeline line */}
                {index < turns.length - 1 && (
                  <div className="bg-border absolute top-10 left-[11px] h-[calc(100%-16px)] w-px" />
                )}

                {/* Icon */}
                <div className="z-10 mt-1 shrink-0">
                  <ActionIcon action={turn.action} />
                </div>

                {/* Content */}
                <div className="mb-6 flex-1 rounded-lg border p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex flex-col gap-1">
                      <div className="flex items-center gap-2">
                        <Link
                          href={`/home/${accountSlug}/executions/${turn.execution_id}`}
                          className="text-primary text-sm font-medium hover:underline"
                        >
                          Turn {turn.sequence_number ?? index}
                        </Link>
                        <ActionBadge action={turn.action} />
                        {turn.corrected && (
                          <Badge
                            variant="outline"
                            className="bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200"
                          >
                            <Wrench className="mr-1 h-3 w-3" />
                            <Trans i18nKey="agentguard:sessions.corrected" />
                          </Badge>
                        )}
                      </div>
                      {turn.task && (
                        <p className="text-muted-foreground text-sm">
                          {turn.task}
                        </p>
                      )}
                    </div>
                    <span
                      className={`text-sm font-semibold ${
                        turn.confidence != null
                          ? turn.confidence >= 0.8
                            ? 'text-green-600 dark:text-green-400'
                            : turn.confidence >= 0.5
                              ? 'text-yellow-600 dark:text-yellow-400'
                              : 'text-red-600 dark:text-red-400'
                          : 'text-muted-foreground'
                      }`}
                    >
                      {formatConfidence(turn.confidence)}
                    </span>
                  </div>

                  {/* Meta row */}
                  <div className="text-muted-foreground mt-3 flex flex-wrap gap-4 text-xs">
                    <span className="flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {formatLatency(turn.latency_ms)}
                    </span>
                    {turn.token_count != null && (
                      <span>{formatTokens(turn.token_count)} tokens</span>
                    )}
                    {turn.cost_estimate != null && (
                      <span>{formatCost(turn.cost_estimate)}</span>
                    )}
                    <span>{formatTimestamp(turn.timestamp)}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function StatPill({
  label,
  value,
}: {
  label: React.ReactNode;
  value: string;
}) {
  return (
    <div className="bg-muted/50 flex flex-col gap-1 rounded-md px-3 py-2">
      <span className="text-muted-foreground text-xs">{label}</span>
      <span className="text-sm font-semibold">{value}</span>
    </div>
  );
}
```

**Step 4: Verify typecheck passes**

Run: `cd nextjs-application && pnpm typecheck`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/web/app/home/[account]/sessions/[sessionId]/
git commit -m "feat(sessions): add session detail page with turn timeline"
```

---

### Task 5: Update Session Links Across Dashboard

**Files:**
- Modify: `apps/web/app/home/[account]/agents/_components/fleet-health-charts.tsx` (SessionRow link)

**Step 1: Update SessionRow to link to the new sessions detail page**

In `fleet-health-charts.tsx`, the `SessionRow` component currently links to the agent detail page. Update the `href` to point to the session detail page instead:

Change:
```typescript
href={`/home/${accountSlug}/agents/${session.agent_id}`}
```

To:
```typescript
href={`/home/${accountSlug}/sessions/${session.session_id}`}
```

**Step 2: Verify typecheck passes**

Run: `cd nextjs-application && pnpm typecheck`
Expected: PASS

**Step 3: Commit**

```bash
git add apps/web/app/home/[account]/agents/_components/fleet-health-charts.tsx
git commit -m "feat(sessions): link fleet session rows to session detail page"
```

---

### Task 6: Final Verification

**Step 1: Run full typecheck**

Run: `cd nextjs-application && pnpm typecheck`
Expected: PASS

**Step 2: Run lint and format**

Run: `cd nextjs-application && pnpm lint:fix && pnpm format:fix`
Expected: PASS

**Step 3: Start dev server and verify pages render**

Run: `cd nextjs-application && pnpm dev`

Verify:
1. Navigate to `/home/test-1/sessions` — sessions list page renders with filter bar and table
2. Click a session row — navigates to `/home/test-1/sessions/<sessionId>` detail page with timeline
3. Sidebar shows "Sessions" under Monitoring section
4. Filters (agent, status, time range) update the URL and table

**Step 4: Commit any lint/format fixes**

```bash
git add -A
git commit -m "chore: lint and format sessions page"
```
