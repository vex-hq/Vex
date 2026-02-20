# Cost & Latency Anomaly Detection (2.5) — Design

## Goal

Complete the anomaly detection pipeline: deliver anomaly alerts via webhook/Slack, surface them on the homepage and agent detail page, and add tests for the detection logic.

## What Already Exists

- `services/alert-service/app/anomaly.py` — Z-score detection for cost and latency against 24h rolling mean/stddev. Configurable sensitivity (default: 3σ). Minimum 10 samples required.
- `services/alert-service/app/worker.py` — Calls `_process_anomalies()` on every event (including pass). Writes anomaly alerts to `alerts` table with deduplication. But does NOT deliver via webhook/Slack.
- `alerts` table already stores `alert_type = 'cost_anomaly' | 'latency_anomaly'` rows.
- `Alert` TypeScript interface in `types.ts` already has `alert_type: string`.
- Homepage already loads `loadAlertSummary()` which counts alerts by severity — anomaly alerts are already counted here.

## Changes

### 1. Webhook/Slack Delivery for Anomaly Alerts

**File:** `services/alert-service/app/worker.py`

Update `_process_anomalies()` to deliver anomaly alerts through the same webhook and Slack channels used for verification alerts. Currently it only writes to DB with `delivered=false`.

Add delivery logic after the DB insert:
- Look up org plan (same `_get_org_plan` call)
- If `webhook_alerts` enabled: call `deliver()` with anomaly-specific payload
- If `slack_alerts` enabled: call `deliver_slack()` with anomaly-specific Slack message
- Update the DB row's `delivered` field

The anomaly webhook payload format:
```json
{
  "event": "anomaly.detected",
  "alert_id": "...",
  "agent_id": "...",
  "execution_id": "...",
  "alert_type": "cost_anomaly",
  "severity": "high",
  "details": {
    "metric": "cost_estimate",
    "value": 0.85,
    "mean_24h": 0.12,
    "stddev_24h": 0.05,
    "z_score": 14.6,
    "threshold": 3.0
  }
}
```

### 2. Slack Message for Anomalies

**File:** `services/alert-service/app/slack.py`

Add `format_anomaly_slack_message()` — Block Kit message with:
- Header: "Cost Anomaly Detected" or "Latency Anomaly Detected"
- Fields: agent, metric value, mean, z-score
- Link to agent detail page

### 3. Homepage Anomaly Alerts Widget

**File:** `apps/web/app/home/[account]/_lib/server/homepage.loader.ts`

New loader `loadAnomalyAlerts(orgId)` — queries alerts table for `alert_type IN ('cost_anomaly', 'latency_anomaly')`, last 7 days, limit 10, joined with agents for name.

**File:** `apps/web/app/home/[account]/_components/homepage-charts.tsx`

New section below failure patterns: "Anomaly Alerts" card showing recent cost/latency anomalies with agent name, metric, value vs mean, severity badge. Empty state: "No anomalies detected."

**File:** `apps/web/app/home/[account]/page.tsx`

Call `loadAnomalyAlerts` in the existing `Promise.all`, pass to dashboard.

### 4. Agent Detail Anomaly Section

**File:** `apps/web/app/home/[account]/agents/[agentId]/_lib/server/agent-detail.loader.ts`

New loader `loadAgentAnomalyAlerts(orgId, agentId)` — same query filtered by agent_id.

**File:** `apps/web/app/home/[account]/agents/[agentId]/_components/agent-detail-charts.tsx`

New section: "Cost & Latency Anomalies" card showing that agent's anomaly alerts.

**File:** `apps/web/app/home/[account]/agents/[agentId]/page.tsx`

Call the new loader, pass to charts.

### 5. TypeScript Types

**File:** `apps/web/lib/agentguard/types.ts`

New interface:
```typescript
export interface AnomalyAlert {
  alert_id: string;
  agent_id: string;
  agent_name: string;
  alert_type: 'cost_anomaly' | 'latency_anomaly';
  severity: 'high' | 'medium';
  created_at: string;
  execution_id: string;
}
```

### 6. Translation Keys

**File:** `apps/web/public/locales/en/agentguard.json`

New keys under `"anomalies"`: title, description, noAnomalies, costAnomaly, latencyAnomaly, zScore, mean, value.

### 7. Tests

**File:** `services/alert-service/tests/test_anomaly.py`

Tests for `detect_anomalies()`:
- No anomaly when cost/latency within normal range
- Cost anomaly triggered when z-score exceeds threshold
- Latency anomaly triggered when z-score exceeds threshold
- No anomaly when insufficient samples (< 10)
- No anomaly when stddev is 0
- Severity escalation (high when z > 4.5)
- None values handled gracefully

**File:** `services/alert-service/tests/test_worker.py` (modify)

Add test for `_process_anomalies` delivering via webhook/Slack.

## Non-Goals

- Configurable sensitivity per agent (use default 3σ for now)
- Historical anomaly trend chart (future)
- Anomaly-specific notification preferences (future)
