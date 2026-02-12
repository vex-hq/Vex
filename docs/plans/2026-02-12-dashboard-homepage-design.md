# Dashboard Homepage Design

## Goal

Replace the MakerKit placeholder homepage with an AgentGuard overview that serves two personas:

1. **Product/business owner** — "How much volume, how reliable, is AgentGuard delivering value?"
2. **Engineering lead** — "Are my agents healthy? Anything on fire?"

A design partner should understand AgentGuard's value in 10 seconds after logging in.

## Layout

Three horizontal bands, all above the fold or with one short scroll.

### Band 1: Value KPI Cards (4 across)

| Card | Data | Subtitle | Color Logic |
|------|------|----------|-------------|
| **Verifications** | Execution count (24h) | "in the last 24 hours" | Neutral |
| **Reliability Score** | Avg confidence (24h) | "across all agents" | Green >= 0.8, Yellow >= 0.5, Red < 0.5 |
| **Issues Caught** | Flag + block count (24h) | "flagged or blocked" | Red if > 0, Green if 0 |
| **Auto-Corrected** | Correction count (24h) | "outputs fixed automatically" | Green if > 0, Neutral if 0 |

The story reads left-to-right: "AgentGuard verified 847 outputs, reliability is 0.87, caught 23 issues, auto-fixed 14."

### Band 2: Executions by Action Chart

- Stacked area chart: pass (green), flag (yellow), block (red)
- 7-day window, hourly buckets
- Reuses existing `loadExecutionsOverTime` loader and Recharts pattern
- Shows volume (stack height) and reliability (green ratio) simultaneously

### Band 3: Agent Health + Alert Summary (side-by-side)

**Left: Agent Health Grid**

Each registered agent as a compact tile/card:
- Agent name (bold, clickable link to detail page)
- Colored health dot: green (confidence >= 0.8), yellow (>= 0.5), red (< 0.5), gray (no data in 24h)
- Confidence score as text (e.g., "0.87")
- 24h execution count (small text, e.g., "142 runs")

Layout: 2-3 column responsive grid. For 1-5 agents this is clean and scannable.

Empty state: "No agents registered yet — send your first execution to get started."

**Right: Alert Summary**

Visual severity indicators (not a table):
- Row of severity pills: `2 Critical` (red) `1 High` (orange) `0 Medium` (gray) `0 Low` (gray)
- Zero-count pills are dimmed/gray
- All-clear state: green checkmark + "All clear — no active alerts"
- "View all alerts" link at bottom

## Data Requirements

### New Loader: `loadHomepageData(orgId)`

Queries needed (all scoped to org_id, 24h window):

1. **KPIs** — Single query aggregating executions:
   - `COUNT(*)` as total_verifications
   - `AVG(confidence)` as avg_confidence
   - `COUNT(*) FILTER (WHERE action IN ('flag', 'block'))` as issues_caught
   - `COUNT(*) FILTER (WHERE corrected = true)` as auto_corrected

2. **Executions over time** — Reuse existing `loadExecutionsOverTime(orgId)` (7d hourly buckets)

3. **Agent health** — Per-agent summary:
   - agent_id, agent name
   - AVG(confidence) last 24h
   - COUNT(*) last 24h
   - Most recent execution timestamp

4. **Alert summary** — Group by severity, count:
   - `COUNT(*) FILTER (WHERE severity = 'critical')` etc.
   - Scoped to last 24h

### Reusable Components

- KPI card style: matches existing fleet health KPI cards
- Chart: same dynamic-import Recharts pattern (SSR disabled)
- Agent tiles: new component, simple card grid
- Alert pills: new component, compact severity badges

## Empty States

For a brand-new design partner with zero data:
- KPI cards show "0" / "—" values
- Chart shows empty state with dashed line or "No data yet"
- Agent grid shows "No agents registered yet" message
- Alert summary shows "All clear"

## Files to Create/Modify

- `app/home/[account]/page.tsx` — Replace placeholder with AgentGuard homepage
- `app/home/[account]/_components/homepage-dashboard.tsx` — Client component (charts)
- `app/home/[account]/_lib/server/homepage.loader.ts` — Data loader
- `app/home/[account]/_components/dashboard-demo.tsx` — Delete (MakerKit placeholder)
- `app/home/[account]/_components/dashboard-demo-charts.tsx` — Delete (MakerKit placeholder)
- `public/locales/en/agentguard.json` — Add homepage i18n strings
