# Pricing Redesign — Design

## Goal

Tighten the Free tier to a sandbox, add a $29/mo Starter tier, bump Pro to $99 and Team to $349, remove agent limits across all tiers, and give Starter 100 corrections/mo as the "aha" hook.

## New Tier Structure

| | Free | Starter | Pro | Team | Enterprise |
|---|---|---|---|---|---|
| Price | $0/mo | $29/mo | $99/mo | $349/mo | Contact Sales |
| Observations | 1,000/mo | 25,000/mo | 150,000/mo | 1,500,000/mo | Custom |
| Verifications | 50/mo | 1,000/mo | 15,000/mo | 150,000/mo | Custom |
| Corrections | None | 100/mo | Full cascade | Full cascade + priority | Custom |
| Agents | Unlimited | Unlimited | Unlimited | Unlimited | Custom |
| Data Retention | 1 day | 7 days | 30 days | 90 days | Custom |
| Support | Community | Email | Email (48h) | Priority (24h) | Custom |

## Changes Required

### Landing Page
- `apps/landing/app/pricing/page.tsx` — rewrite `plans` array with 5 tiers

### Backend Plan Config (Python)
- `services/shared/shared/plan_limits.py` — add `starter` tier, add `corrections_per_month` field, update all tier values, remove `max_agents` limits (set all to -1)

### Frontend Plan Config (TypeScript)
- `apps/web/lib/agentguard/plan-limits.ts` — mirror Python changes

### Database Migration
- New Supabase migration — update CHECK constraint to include `'starter'`

### Admin UI
- `apps/web/app/admin/accounts/[id]/_components/plan-management.tsx` — add `starter` to dropdown
- `apps/web/app/admin/accounts/[id]/_lib/update-plan.action.ts` — add `starter` to Zod enum

### Dashboard
- `apps/web/app/home/[account]/_components/homepage-charts.tsx` — Starter has 100 corrections, so show corrections meter for Starter too

### Tests
- `scripts/test_plan_enforcement.py` — remove agent-limit test (now unlimited)
