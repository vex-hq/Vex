# Cost & Latency Anomaly Detection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete the anomaly detection pipeline — deliver anomaly alerts via webhook/Slack, surface them on homepage and agent detail page, and add tests.

**Architecture:** The Z-score detection logic (`anomaly.py`) and alert worker wiring (`_process_anomalies`) already exist. We add delivery to the anomaly processing, a Slack formatter for anomalies, dashboard loaders + UI sections on homepage and agent detail, and comprehensive tests.

**Tech Stack:** Python (alert-service), Next.js 16 (App Router), TypeScript, Neon Postgres, Recharts

---

### Task 1: Tests for anomaly detection

**Files:**
- Create: `services/alert-service/tests/test_anomaly.py`

**Step 1: Write the tests**

```python
"""Tests for Z-score based cost and latency anomaly detection."""

from unittest.mock import MagicMock

from app.anomaly import detect_anomalies, MIN_SAMPLES


def _mock_db_with_stats(
    cost_count=20, cost_mean=0.10, cost_stddev=0.02,
    latency_count=20, latency_mean=500.0, latency_stddev=50.0,
):
    """Return a mock db_session that returns the given agent stats."""
    mock = MagicMock()
    mock.execute.return_value.fetchone.return_value = (
        cost_count, cost_mean, cost_stddev,
        latency_count, latency_mean, latency_stddev,
    )
    return mock


def _mock_db_no_data():
    mock = MagicMock()
    mock.execute.return_value.fetchone.return_value = None
    return mock


def test_no_anomaly_within_normal_range():
    db = _mock_db_with_stats()
    event = {"agent_id": "bot-1", "execution_id": "e1", "cost_estimate": 0.12, "latency_ms": 550}
    result = detect_anomalies(event, db)
    assert result == []


def test_cost_anomaly_triggered():
    db = _mock_db_with_stats(cost_mean=0.10, cost_stddev=0.02)
    event = {"agent_id": "bot-1", "execution_id": "e1", "cost_estimate": 0.50, "latency_ms": 500}
    result = detect_anomalies(event, db)
    assert len(result) == 1
    assert result[0]["alert_type"] == "cost_anomaly"
    assert result[0]["details"]["z_score"] > 3.0


def test_latency_anomaly_triggered():
    db = _mock_db_with_stats(latency_mean=500.0, latency_stddev=50.0)
    event = {"agent_id": "bot-1", "execution_id": "e1", "cost_estimate": 0.10, "latency_ms": 900}
    result = detect_anomalies(event, db)
    assert len(result) == 1
    assert result[0]["alert_type"] == "latency_anomaly"
    assert result[0]["details"]["z_score"] > 3.0


def test_both_anomalies_triggered():
    db = _mock_db_with_stats(cost_mean=0.10, cost_stddev=0.02, latency_mean=500.0, latency_stddev=50.0)
    event = {"agent_id": "bot-1", "execution_id": "e1", "cost_estimate": 0.50, "latency_ms": 900}
    result = detect_anomalies(event, db)
    assert len(result) == 2
    types = {r["alert_type"] for r in result}
    assert types == {"cost_anomaly", "latency_anomaly"}


def test_insufficient_samples_skips():
    db = _mock_db_with_stats(cost_count=5, latency_count=5)
    event = {"agent_id": "bot-1", "execution_id": "e1", "cost_estimate": 999, "latency_ms": 99999}
    result = detect_anomalies(event, db)
    assert result == []


def test_zero_stddev_skips():
    db = _mock_db_with_stats(cost_stddev=0.0, latency_stddev=0.0)
    event = {"agent_id": "bot-1", "execution_id": "e1", "cost_estimate": 999, "latency_ms": 99999}
    result = detect_anomalies(event, db)
    assert result == []


def test_no_db_data_skips():
    db = _mock_db_no_data()
    event = {"agent_id": "bot-1", "execution_id": "e1", "cost_estimate": 0.50}
    result = detect_anomalies(event, db)
    assert result == []


def test_none_values_handled():
    db = _mock_db_with_stats()
    event = {"agent_id": "bot-1", "execution_id": "e1"}
    result = detect_anomalies(event, db)
    assert result == []


def test_severity_escalation_high():
    # z > 4.5 (sensitivity * 1.5) → high severity
    db = _mock_db_with_stats(cost_mean=0.10, cost_stddev=0.02)
    event = {"agent_id": "bot-1", "execution_id": "e1", "cost_estimate": 0.50}
    result = detect_anomalies(event, db)
    assert result[0]["severity"] == "high"  # z = 20, well above 4.5


def test_severity_medium():
    # z between 3 and 4.5 → medium severity
    db = _mock_db_with_stats(cost_mean=0.10, cost_stddev=0.02)
    # cost=0.17 → z = (0.17 - 0.10) / 0.02 = 3.5
    event = {"agent_id": "bot-1", "execution_id": "e1", "cost_estimate": 0.17}
    result = detect_anomalies(event, db)
    assert result[0]["severity"] == "medium"
```

**Step 2: Run tests**

Run: `cd services/alert-service && .venv/bin/python -m pytest tests/test_anomaly.py -v`
Expected: All 10 tests PASS

**Step 3: Commit**

```bash
git add services/alert-service/tests/test_anomaly.py
git commit -m "test: add unit tests for Z-score anomaly detection"
```

---

### Task 2: Anomaly alert delivery via webhook/Slack

**Files:**
- Modify: `services/alert-service/app/slack.py` (add `format_anomaly_slack_message`)
- Modify: `services/alert-service/app/worker.py` (update `_process_anomalies` to deliver)

**Step 1: Add anomaly Slack formatter**

In `services/alert-service/app/slack.py`, add after `format_slack_message`:

```python
def format_anomaly_slack_message(
    alert_id: str,
    agent_id: str,
    execution_id: str,
    alert_type: str,
    severity: str,
    details: Dict[str, Any],
    dashboard_base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a Slack Block Kit message for a cost/latency anomaly alert."""
    emoji = _severity_emoji(severity)
    metric = details.get("metric", "unknown")
    value = details.get("value", 0)
    mean = details.get("mean_24h", 0)
    z_score = details.get("z_score", 0)

    metric_label = "Cost" if "cost" in metric else "Latency"
    unit = "" if "cost" in metric else "ms"

    header_text = f"{emoji} *{metric_label} Anomaly* detected for agent *{agent_id}*"

    blocks: List[Dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{metric_label} Anomaly Detected", "emoji": True},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": header_text},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Agent:*\n{agent_id}"},
                {"type": "mrkdwn", "text": f"*Severity:*\n{severity}"},
                {"type": "mrkdwn", "text": f"*Current Value:*\n{value}{unit}"},
                {"type": "mrkdwn", "text": f"*24h Mean:*\n{mean}{unit}"},
                {"type": "mrkdwn", "text": f"*Z-Score:*\n{z_score}"},
                {"type": "mrkdwn", "text": f"*Execution:*\n`{execution_id}`"},
            ],
        },
    ]

    if dashboard_base_url:
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View in Dashboard"},
                    "url": f"{dashboard_base_url}/executions/{execution_id}",
                },
            ],
        })

    blocks.append({"type": "divider"})
    return {"blocks": blocks}
```

**Step 2: Update `_process_anomalies` for delivery**

In `services/alert-service/app/worker.py`, replace the entire `_process_anomalies` function:

```python
async def _process_anomalies(
    event_data: Dict[str, Any],
    db_session: object,
) -> None:
    """Run anomaly detection and create/deliver alerts for any anomalies found."""
    agent_id = event_data.get("agent_id", "")
    execution_id = event_data.get("execution_id", "")
    org_id = event_data.get("org_id", DEFAULT_ORG)

    try:
        anomalies = detect_anomalies(event_data, db_session)
    except Exception:
        logger.warning("Anomaly detection failed for %s", execution_id, exc_info=True)
        return

    if not anomalies:
        return

    # Look up org plan for delivery gating
    plan = _get_org_plan(org_id, db_session)
    plan_config = get_plan_config(plan)
    now = datetime.now(timezone.utc)

    for anomaly in anomalies:
        alert_type = anomaly["alert_type"]

        # Dedup anomaly alerts the same way
        should_send, _ = _deduplicator.should_deliver(agent_id, alert_type)
        if not should_send:
            continue

        alert_id = str(uuid.uuid4())
        delivered = False
        slack_delivered = False
        webhook_url = None
        response_status = None
        delivery_attempts = 0

        # Webhook delivery
        if plan_config.webhook_alerts:
            webhook_url = get_webhook_url(agent_id)
            if webhook_url:
                payload = {
                    "event": "anomaly.detected",
                    "alert_id": alert_id,
                    "agent_id": agent_id,
                    "execution_id": execution_id,
                    "alert_type": alert_type,
                    "severity": anomaly["severity"],
                    "details": anomaly["details"],
                }
                delivered, response_status = await deliver(webhook_url, payload)
                delivery_attempts = 3 if not delivered else 1

        # Slack delivery
        if plan_config.slack_alerts:
            slack_url = get_slack_webhook_url(agent_id)
            if slack_url:
                from app.slack import format_anomaly_slack_message
                slack_payload = format_anomaly_slack_message(
                    alert_id=alert_id,
                    agent_id=agent_id,
                    execution_id=execution_id,
                    alert_type=alert_type,
                    severity=anomaly["severity"],
                    details=anomaly["details"],
                    dashboard_base_url=DASHBOARD_BASE_URL,
                )
                slack_delivered, _ = await deliver_slack(slack_url, slack_payload)

        any_delivered = delivered or slack_delivered

        db_session.execute(
            text("""
                INSERT INTO alerts (
                    alert_id, execution_id, agent_id, org_id,
                    alert_type, severity, delivered,
                    webhook_url, delivery_attempts, last_attempt_at, response_status,
                    created_at
                ) VALUES (
                    :alert_id, :execution_id, :agent_id, :org_id,
                    :alert_type, :severity, :delivered,
                    :webhook_url, :delivery_attempts, :last_attempt_at, :response_status,
                    :created_at
                )
            """),
            {
                "alert_id": alert_id,
                "execution_id": execution_id,
                "agent_id": agent_id,
                "org_id": org_id,
                "alert_type": alert_type,
                "severity": anomaly["severity"],
                "delivered": any_delivered,
                "webhook_url": webhook_url,
                "delivery_attempts": delivery_attempts,
                "last_attempt_at": now if (webhook_url or slack_delivered) else None,
                "response_status": response_status,
                "created_at": now,
            },
        )
        db_session.commit()

        logger.info(
            "Anomaly alert %s created: %s (z=%.2f) for execution %s (delivered=%s, slack=%s)",
            alert_id,
            alert_type,
            anomaly["details"].get("z_score", 0),
            execution_id,
            delivered,
            slack_delivered,
        )
```

**Important:** Since `_process_anomalies` now uses `await`, change its signature from `def` to `async def` and update the call site in `process_verified_event` from `_process_anomalies(event_data, db_session)` to `await _process_anomalies(event_data, db_session)`.

**Step 3: Run existing tests to confirm no regressions**

Run: `cd services/alert-service && .venv/bin/python -m pytest tests/ -v`
Expected: All existing tests PASS (test_worker.py tests mock `_process_anomalies` indirectly via `detect_anomalies`)

**Step 4: Commit**

```bash
git add services/alert-service/app/slack.py services/alert-service/app/worker.py
git commit -m "feat: deliver anomaly alerts via webhook and Slack"
```

---

### Task 3: TypeScript types and translation keys

**Files:**
- Modify: `apps/web/lib/agentguard/types.ts`
- Modify: `apps/web/public/locales/en/agentguard.json`

**Step 1: Add AnomalyAlert type**

In `apps/web/lib/agentguard/types.ts`, add after the existing `ToolAnomaly` interface:

```typescript
export interface AnomalyAlert {
  alert_id: string;
  agent_id: string;
  agent_name: string;
  alert_type: 'cost_anomaly' | 'latency_anomaly';
  severity: 'high' | 'medium';
  execution_id: string;
  created_at: string;
}
```

**Step 2: Add translation keys**

In `apps/web/public/locales/en/agentguard.json`, add to the root object:

```json
"anomalies": {
  "title": "Cost & Latency Anomalies",
  "description": "Z-score based anomaly alerts from the last 7 days",
  "noAnomalies": "No anomalies detected — all agents operating within normal ranges.",
  "costAnomaly": "Cost Anomaly",
  "latencyAnomaly": "Latency Anomaly",
  "agentLabel": "Agent",
  "detectedAt": "Detected"
}
```

**Step 3: Commit**

```bash
cd nextjs-application
git add apps/web/lib/agentguard/types.ts apps/web/public/locales/en/agentguard.json
git commit -m "feat: add AnomalyAlert type and i18n keys for anomaly dashboard"
```

---

### Task 4: Homepage anomaly alerts loader and widget

**Files:**
- Modify: `apps/web/app/home/[account]/_lib/server/homepage.loader.ts`
- Modify: `apps/web/app/home/[account]/_components/homepage-charts.tsx`
- Modify: `apps/web/app/home/[account]/_components/homepage-dashboard.tsx`
- Modify: `apps/web/app/home/[account]/page.tsx`

**Step 1: Add loader**

In `apps/web/app/home/[account]/_lib/server/homepage.loader.ts`, add at the end:

```typescript
import type { AnomalyAlert } from '~/lib/agentguard/types';

// (add AnomalyAlert to the existing import if types is already imported)

/**
 * Load recent cost/latency anomaly alerts for the homepage (last 7 days).
 */
export const loadAnomalyAlerts = cache(
  async (orgId: string): Promise<AnomalyAlert[]> => {
    const pool = getAgentGuardPool();

    const result = await pool.query<AnomalyAlert>(
      `
      SELECT
        al.alert_id,
        al.agent_id,
        COALESCE(ag.name, al.agent_id) AS agent_name,
        al.alert_type,
        al.severity,
        al.execution_id,
        al.created_at
      FROM alerts al
      LEFT JOIN agents ag ON al.agent_id = ag.agent_id
      WHERE al.org_id = $1
        AND al.alert_type IN ('cost_anomaly', 'latency_anomaly')
        AND al.created_at >= NOW() - INTERVAL '7 days'
      ORDER BY al.created_at DESC
      LIMIT 10
      `,
      [orgId],
    );

    return result.rows;
  },
);
```

**Step 2: Update page.tsx to load anomaly alerts**

In `apps/web/app/home/[account]/page.tsx`:
- Add `loadAnomalyAlerts` to the imports from `homepage.loader`
- Add it to the `Promise.all` array
- Pass `anomalyAlerts` to `HomepageDashboard`

The Promise.all line becomes:
```typescript
const [kpis, agentHealth, alertSummary, trend, planUsage, failurePatterns, anomalyAlerts] =
  await Promise.all([
    loadHomepageKpis(orgId),
    loadAgentHealth(orgId),
    loadAlertSummary(orgId),
    loadHomepageTrend(orgId),
    loadPlanUsage(orgId, account),
    loadFailurePatterns(orgId),
    loadAnomalyAlerts(orgId),
  ]);
```

And the JSX:
```tsx
<HomepageDashboard
  kpis={kpis}
  agentHealth={agentHealth}
  alertSummary={alertSummary}
  trend={trend}
  accountSlug={account}
  planUsage={planUsage}
  failurePatterns={failurePatterns}
  anomalyAlerts={anomalyAlerts}
/>
```

**Step 3: Update HomepageDashboard to accept and pass anomalyAlerts**

In `apps/web/app/home/[account]/_components/homepage-dashboard.tsx`, add `anomalyAlerts` to the props interface and pass it through to `HomepageCharts` (or the charts component within the dynamic import).

**Step 4: Add anomaly alerts widget to homepage-charts.tsx**

In `apps/web/app/home/[account]/_components/homepage-charts.tsx`, add a new section after the Failure Patterns widget. Pattern: Card with header, list of anomaly alerts showing severity badge, alert type label, agent name, and relative time. Use the same card/badge patterns as existing sections.

```tsx
{/* Anomaly Alerts */}
<Card>
  <CardHeader>
    <CardTitle className="text-base">
      <Trans i18nKey="agentguard:anomalies.title" />
    </CardTitle>
    <CardDescription>
      <Trans i18nKey="agentguard:anomalies.description" />
    </CardDescription>
  </CardHeader>
  <CardContent>
    {anomalyAlerts.length === 0 ? (
      <p className="text-muted-foreground py-4 text-sm">
        <Trans i18nKey="agentguard:anomalies.noAnomalies" />
      </p>
    ) : (
      <div className="space-y-3">
        {anomalyAlerts.map((alert) => (
          <div
            key={alert.alert_id}
            className="flex items-center justify-between rounded-md border px-3 py-2"
          >
            <div className="flex items-center gap-3">
              <Badge
                variant="outline"
                className={
                  alert.severity === 'high'
                    ? 'bg-red-500/15 text-red-400 border-red-500/30'
                    : 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30'
                }
              >
                {alert.severity}
              </Badge>
              <div>
                <p className="text-sm font-medium">
                  <Trans
                    i18nKey={
                      alert.alert_type === 'cost_anomaly'
                        ? 'agentguard:anomalies.costAnomaly'
                        : 'agentguard:anomalies.latencyAnomaly'
                    }
                  />
                </p>
                <p className="text-muted-foreground text-xs">
                  {alert.agent_name}
                </p>
              </div>
            </div>
            <span className="text-muted-foreground text-xs">
              {formatDistanceToNow(new Date(alert.created_at), { addSuffix: true })}
            </span>
          </div>
        ))}
      </div>
    )}
  </CardContent>
</Card>
```

Note: Import `formatDistanceToNow` from `date-fns` (already a dependency — check existing imports in the file).

**Step 5: Run typecheck**

Run: `cd nextjs-application && pnpm typecheck`
Expected: No new errors in our files

**Step 6: Commit**

```bash
cd nextjs-application
git add apps/web/app/home/[account]/_lib/server/homepage.loader.ts \
  apps/web/app/home/[account]/_components/homepage-charts.tsx \
  apps/web/app/home/[account]/_components/homepage-dashboard.tsx \
  apps/web/app/home/[account]/page.tsx
git commit -m "feat: add anomaly alerts widget to homepage dashboard"
```

---

### Task 5: Agent detail anomaly section

**Files:**
- Modify: `apps/web/app/home/[account]/agents/[agentId]/_lib/server/agent-detail.loader.ts`
- Modify: `apps/web/app/home/[account]/agents/[agentId]/_components/agent-detail-charts.tsx`
- Modify: `apps/web/app/home/[account]/agents/[agentId]/_components/agent-detail-dashboard.tsx`
- Modify: `apps/web/app/home/[account]/agents/[agentId]/page.tsx`

**Step 1: Add loader**

In `apps/web/app/home/[account]/agents/[agentId]/_lib/server/agent-detail.loader.ts`, add:

```typescript
import type { AnomalyAlert } from '~/lib/agentguard/types';

export const loadAgentAnomalyAlerts = cache(
  async (agentId: string): Promise<AnomalyAlert[]> => {
    const pool = getAgentGuardPool();

    const result = await pool.query<AnomalyAlert>(
      `
      SELECT
        al.alert_id,
        al.agent_id,
        COALESCE(ag.name, al.agent_id) AS agent_name,
        al.alert_type,
        al.severity,
        al.execution_id,
        al.created_at
      FROM alerts al
      LEFT JOIN agents ag ON al.agent_id = ag.agent_id
      WHERE al.agent_id = $1
        AND al.alert_type IN ('cost_anomaly', 'latency_anomaly')
        AND al.created_at >= NOW() - INTERVAL '7 days'
      ORDER BY al.created_at DESC
      LIMIT 10
      `,
      [agentId],
    );

    return result.rows;
  },
);
```

**Step 2: Update page.tsx**

In `apps/web/app/home/[account]/agents/[agentId]/page.tsx`:
- Add `loadAgentAnomalyAlerts` to imports
- Add to `Promise.all`
- Pass `anomalyAlerts` to `AgentDetailDashboard`

**Step 3: Update dashboard and charts**

Follow the same pattern as Task 4 — add `anomalyAlerts` prop to `AgentDetailDashboard`, pass to `AgentDetailCharts`, render the same anomaly alerts card (without the agent name column since it's agent-specific).

**Step 4: Run typecheck**

Run: `cd nextjs-application && pnpm typecheck`
Expected: No new errors in our files

**Step 5: Commit**

```bash
cd nextjs-application
git add apps/web/app/home/[account]/agents/[agentId]/_lib/server/agent-detail.loader.ts \
  apps/web/app/home/[account]/agents/[agentId]/_components/agent-detail-charts.tsx \
  apps/web/app/home/[account]/agents/[agentId]/_components/agent-detail-dashboard.tsx \
  apps/web/app/home/[account]/agents/[agentId]/page.tsx
git commit -m "feat: add anomaly alerts section to agent detail page"
```

---

### Task 6: Final verification

**Step 1: Run all Python tests**

```bash
cd services/alert-service && .venv/bin/python -m pytest tests/ -v
```

Expected: All tests pass

**Step 2: Run TypeScript checks**

```bash
cd nextjs-application && pnpm typecheck && pnpm lint:fix && pnpm format:fix
```

Expected: No new errors in our files

**Step 3: Visual verification**

Start dev server, navigate to homepage — verify anomaly alerts widget renders (empty state if no anomaly data). Navigate to agent detail page — verify anomaly section renders.
