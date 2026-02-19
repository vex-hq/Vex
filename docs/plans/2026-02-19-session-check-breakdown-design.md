# Session Check Results Breakdown

**Date:** 2026-02-19
**Status:** Approved

## Problem

The session detail page shows an aggregate confidence score per turn but does not surface the individual verification check results (schema, hallucination, drift, coherence). Developers cannot tell *which* check failed without navigating to the execution detail page.

## Solution

Surface per-check scores from the existing `check_results` table directly on the session timeline, as a collapsible panel below each turn's VerificationBar.

## Changes

### 1. Data Layer — `sessions.loader.ts`

Add `loadSessionCheckResults(turns: SessionTurn[])` that:
- Collects all `execution_id` values from the turns
- Queries `check_results` table: `SELECT * FROM check_results WHERE execution_id = ANY($1)`
- Returns `Record<string, CheckResult[]>` keyed by execution_id

### 2. Props Flow

- `page.tsx`: call `loadSessionCheckResults(turns)` alongside trace payloads
- Pass `checkResults` map through `SessionDetailDashboard` → `SessionTimeline`
- Each `ConversationTurnView` and `FallbackTurnView` receives its check results

### 3. UI — `CheckBreakdown` component

Collapsible panel below VerificationBar showing:
- One row per check: icon, check type label, pass/fail badge, score (color-coded)
- Expandable details (JSONB `details` field) per check
- Collapsed by default to keep timeline clean

### What doesn't change

- No new DB tables or migrations
- No new API endpoints or backend services
- Existing VerificationBar unchanged
- `CheckResult` type already exists in `types.ts`
