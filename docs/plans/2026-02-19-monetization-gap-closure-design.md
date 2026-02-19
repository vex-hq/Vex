# Monetization Gap Closure Design

## Context

The initial monetization implementation (10 tasks) built scaffolding: pricing page, billing config, plan limits, quota enforcement code, correction gating, usage meter UI, seat limits, and retention migration. However, several critical gaps remain before monetization is production-ready.

Stripe integration is explicitly deferred until a Stripe account is set up.

## Gap 1: Enterprise Plan with Custom Per-Org Overrides

**Problem:** No enterprise tier exists. Enterprise clients need custom limits.

**Solution:**
- New Alembic migration: add `plan_overrides JSONB DEFAULT NULL` to `organizations`
- Add `enterprise` tier to `plan_limits.py` and `plan-limits.ts` with generous defaults:
  - 10M observations/mo, 1M verifications/mo, unlimited agents/seats, 365-day retention, 10K RPM
- Update `get_plan_config()` (Python) and `getPlanLimits()` (TypeScript) to merge org-specific overrides on top of plan defaults
- Add "Plan Management" section to super admin account detail page (`/admin/accounts/[id]`):
  - Plan selector dropdown (free/pro/team/enterprise)
  - Custom limit override fields
  - Server action using admin client to update `organizations.plan` + `plan_overrides`

## Gap 2: Wire Real Usage Data to Dashboard

**Problem:** Usage meters show hardcoded zeros.

**Solution:**
- Create server function to query `hourly_agent_stats` continuous aggregate for current month execution counts per org
- Split by scope: observations (async/ingest) vs verifications (sync/verify) — this may require a new column or tagging in the stats table
- Pass real counts + plan limits (with overrides) to `UsageMeter` components
- Show current plan name and upgrade link

## Gap 3: Backend Agent Limit Enforcement

**Problem:** Seat limits enforced on dashboard. Agent limits not enforced anywhere on backend.

**Solution:**
- Add agent count check to ingestion API and sync gateway routes
- When a request arrives with an `agent_id` not previously seen for the org, query `COUNT(DISTINCT agent_id)` from `executions` for that org
- If count >= `plan_config.max_agents` (and max_agents != -1), reject with 403 + upgrade message
- Cache known agent IDs per org in `KeyValidator` to avoid DB query on every request

## Gap 4: Retention Cron Script

**Problem:** `enforce_plan_retention()` SQL function exists but nothing calls it.

**Solution:**
- Create `services/scripts/run_retention.py` — connects to DB, calls `SELECT enforce_plan_retention()`
- Document scheduling options: system cron, Docker cron entry, or `pg_cron` extension
- Recommended: daily at 3 AM UTC

## Gap 5: End-to-End Testing

**Problem:** Nothing tested at runtime. All changes are compile-verified only.

**Solution:**
- Create `scripts/test_quota_enforcement.py`:
  - Sends events via SDK until quota exceeded
  - Verifies 429 response with upgrade message
  - Tests both observation and verification quotas
- Create `scripts/test_correction_gating.py`:
  - Sends verify request on free plan with correction=cascade
  - Verifies `correction_skipped: true` in response
- Create `scripts/test_plan_enforcement.py`:
  - Tests rate limiting respects plan RPM cap
  - Tests agent limit enforcement
- Manual test checklist for dashboard UI

## Gap 6: Stripe Integration (Deferred)

Explicitly deferred until Stripe account is ready. When the time comes:
- Create 4 Stripe products (Pro Monthly/Yearly, Team Monthly/Yearly) in test mode
- Replace `price_vex_*` placeholders in `billing.config.ts`
- Wire Stripe checkout success webhook → update `organizations.plan`
- Wire subscription cancellation webhook → downgrade to free
- Add Stripe metered billing for overage (observation + verification usage reporting)

## Implementation Priority

1. Enterprise plan + admin UI (Gap 1) — highest business value
2. Real usage data in dashboard (Gap 2) — makes the product feel real
3. Agent limit enforcement (Gap 3) — closes enforcement gap
4. Retention cron (Gap 4) — quick win
5. E2E testing (Gap 5) — validates everything works
