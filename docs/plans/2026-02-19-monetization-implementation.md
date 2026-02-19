# Monetization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement 3-tier pricing (Free/Pro/Team) with Stripe billing, backend quota enforcement, and a pricing page on the landing site.

**Architecture:** Landing site gets a `/pricing` page. Dashboard billing config is updated with real Vex plans. Backend `KeyValidator` is extended with plan-aware quota checking. Dashboard gets usage meters and upgrade prompts.

**Tech Stack:** Next.js 16 (App Router), Stripe (via Makerkit billing packages), FastAPI (Python backend), TimescaleDB, Tailwind CSS 4

---

### Task 1: Pricing Page on Landing Site

**Files:**
- Create: `apps/landing/app/pricing/page.tsx`
- Modify: `apps/landing/app/_components/site-header.tsx` (add Pricing nav link)
- Modify: `apps/landing/app/sitemap.ts` (add /pricing route)
- Modify: `apps/landing/public/llms.txt` (add pricing link)

**Step 1: Create the pricing page**

Create `apps/landing/app/pricing/page.tsx`:

```tsx
import type { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Pricing — Vex',
  description:
    'Simple, transparent pricing for AI agent runtime reliability. Free tier included. No credit card required.',
  keywords: [
    'Vex pricing',
    'AI agent monitoring pricing',
    'LLM guardrails pricing',
  ],
};

const plans = [
  {
    name: 'Free',
    price: '$0',
    period: '/mo',
    description: 'For experimenting with agent reliability',
    cta: 'Get Started Free',
    ctaHref: 'https://app.tryvex.dev',
    highlighted: false,
    features: [
      '10,000 observations/mo',
      '500 verifications/mo',
      '3 agents',
      '1 seat',
      '7-day retention',
      '100 RPM rate limit',
      'Email alerts',
      'Community support',
    ],
    limits: [
      'No corrections',
      'Hard usage limits',
    ],
  },
  {
    name: 'Pro',
    price: '$79',
    yearlyPrice: '$66',
    period: '/mo',
    description: 'For teams shipping agents to production',
    cta: 'Start Pro',
    ctaHref: 'https://app.tryvex.dev',
    highlighted: true,
    badge: 'Most Popular',
    features: [
      '100,000 observations/mo',
      '10,000 verifications/mo',
      '15 agents',
      '5 seats',
      '30-day retention',
      '1,000 RPM rate limit',
      'Full 3-layer correction cascade',
      'Email + webhook alerts',
      'Email support (48h SLA)',
      'Overage: $0.0005/obs, $0.005/verify',
    ],
    limits: [],
  },
  {
    name: 'Team',
    price: '$299',
    yearlyPrice: '$249',
    period: '/mo',
    description: 'For scaling teams with mission-critical agents',
    cta: 'Start Team',
    ctaHref: 'https://app.tryvex.dev',
    highlighted: false,
    features: [
      '1,000,000 observations/mo',
      '100,000 verifications/mo',
      'Unlimited agents',
      '15 seats',
      '90-day retention',
      '5,000 RPM rate limit',
      'Full correction cascade + priority',
      'Email + webhook + Slack alerts',
      'Priority support (24h SLA)',
      'Overage: $0.0004/obs, $0.004/verify',
    ],
    limits: [],
  },
];

const faqs = [
  {
    q: 'What counts as an observation?',
    a: 'An observation is any event sent to Vex via the SDK in async mode — LLM calls, tool executions, agent actions. Observations are lightweight and add zero latency to your agent.',
  },
  {
    q: 'What counts as a verification?',
    a: 'A verification is a sync call to the /v1/verify endpoint where Vex checks your agent\'s output for hallucinations, schema violations, and task drift before it reaches the user.',
  },
  {
    q: 'What happens when I exceed my plan limits?',
    a: 'On the Free plan, requests are rejected with a 429 status. On Pro and Team, overage is billed automatically at the listed per-unit rate — no interruption to your agents.',
  },
  {
    q: 'Can I switch plans at any time?',
    a: 'Yes. Upgrades take effect immediately with prorated billing. Downgrades take effect at the end of your current billing period.',
  },
  {
    q: 'Do you offer annual billing?',
    a: 'Yes. Annual billing saves ~20% — Pro drops to $66/mo ($790/yr) and Team drops to $249/mo ($2,990/yr).',
  },
  {
    q: 'Is Vex open source?',
    a: 'The Vex SDK is open source (Apache 2.0). The managed cloud platform (dashboard, verification engine, correction cascade) is the paid product.',
  },
];

export default function PricingPage() {
  return (
    <div className="container py-24">
      {/* Hero */}
      <div className="mb-16 text-center">
        <div className="mb-4 text-[13px] font-medium uppercase tracking-widest text-emerald-500">
          Pricing
        </div>
        <h1 className="mb-4 text-3xl font-bold text-white sm:text-4xl lg:text-5xl">
          Simple, transparent pricing
        </h1>
        <p className="mx-auto max-w-[520px] text-[17px] leading-relaxed text-[#a2a2a2]">
          Start free. Scale as your agents grow. No credit card required.
        </p>
      </div>

      {/* Plan cards */}
      <div className="mx-auto mb-24 grid max-w-[1100px] gap-8 lg:grid-cols-3">
        {plans.map((plan) => (
          <div
            key={plan.name}
            className={`relative rounded-xl border p-8 ${
              plan.highlighted
                ? 'border-emerald-500/40 bg-emerald-500/5'
                : 'border-[#252525] bg-[#0a0a0a]'
            }`}
          >
            {plan.badge && (
              <span className="absolute -top-3 left-6 rounded-full bg-emerald-500 px-3 py-1 text-[11px] font-semibold text-white">
                {plan.badge}
              </span>
            )}
            <h2 className="mb-2 text-xl font-bold text-white">{plan.name}</h2>
            <p className="mb-6 text-sm text-[#a2a2a2]">{plan.description}</p>
            <div className="mb-8">
              <span className="text-4xl font-bold text-white">{plan.price}</span>
              <span className="text-[#585858]">{plan.period}</span>
              {plan.yearlyPrice && (
                <span className="ml-2 text-sm text-emerald-500">
                  {plan.yearlyPrice}/mo billed yearly
                </span>
              )}
            </div>
            <Link
              href={plan.ctaHref}
              className={`mb-8 flex h-12 items-center justify-center rounded-lg text-[15px] font-semibold transition-colors ${
                plan.highlighted
                  ? 'bg-emerald-500 text-white hover:bg-emerald-400'
                  : 'border border-[#252525] text-[#a2a2a2] hover:border-[#585858] hover:text-white'
              }`}
            >
              {plan.cta}
            </Link>
            <ul className="space-y-3">
              {plan.features.map((f) => (
                <li key={f} className="flex items-start gap-2 text-sm text-[#a2a2a2]">
                  <span className="mt-0.5 text-emerald-500">✓</span>
                  {f}
                </li>
              ))}
              {plan.limits.map((l) => (
                <li key={l} className="flex items-start gap-2 text-sm text-[#585858]">
                  <span className="mt-0.5">—</span>
                  {l}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {/* Enterprise CTA */}
      <div className="mx-auto mb-24 max-w-[800px] rounded-xl border border-[#252525] bg-[#0a0a0a] p-10 text-center">
        <h2 className="mb-3 text-2xl font-bold text-white">Need more?</h2>
        <p className="mb-6 text-[#a2a2a2]">
          Custom limits, SSO, dedicated support, SLA guarantees, and self-hosted
          deployment options for enterprise teams.
        </p>
        <Link
          href="mailto:hello@tryvex.dev"
          className="inline-flex h-12 items-center rounded-lg border border-[#252525] px-7 text-[15px] font-medium text-[#a2a2a2] transition-colors hover:border-[#585858] hover:text-white"
        >
          Contact Sales
        </Link>
      </div>

      {/* FAQ */}
      <div className="mx-auto max-w-[700px]">
        <h2 className="mb-8 text-center text-2xl font-bold text-white">
          Frequently Asked Questions
        </h2>
        <div className="space-y-6">
          {faqs.map((faq) => (
            <div key={faq.q} className="border-b border-[#252525] pb-6">
              <h3 className="mb-2 font-medium text-white">{faq.q}</h3>
              <p className="text-sm leading-relaxed text-[#a2a2a2]">{faq.a}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
```

**Step 2: Add Pricing to site header**

In `apps/landing/app/_components/site-header.tsx`, add a "Pricing" link between "Blog" and "Docs" in the nav links array.

**Step 3: Add to sitemap**

In `apps/landing/app/sitemap.ts`, add:
```typescript
{
  url: 'https://tryvex.dev/pricing',
  lastModified: new Date(),
  changeFrequency: 'monthly',
  priority: 0.9,
},
```

**Step 4: Add to llms.txt**

In `apps/landing/public/llms.txt`, add under Links:
```
- Pricing: https://tryvex.dev/pricing
```

**Step 5: Verify build**

Run: `cd apps/landing && pnpm build`
Expected: Build succeeds, `/pricing` page renders

**Step 6: Commit**

```bash
git add apps/landing/app/pricing/ apps/landing/app/_components/site-header.tsx apps/landing/app/sitemap.ts apps/landing/public/llms.txt
git commit -m "feat: add pricing page with 3-tier plan comparison"
```

---

### Task 2: Update Billing Config with Vex Plans

**Files:**
- Modify: `apps/web/config/billing.config.ts`

**Context:** The billing config currently re-exports `billing.sample.config.ts` which has Makerkit placeholder plans. We need to replace it with Vex-specific plans. The Stripe price IDs will be placeholders until Stripe products are created — use descriptive IDs like `price_vex_pro_monthly` that can be search-and-replaced later.

**Step 1: Replace billing.config.ts with Vex plans**

Replace the content of `apps/web/config/billing.config.ts` with:

```typescript
import { BillingProviderSchema, createBillingSchema } from '@kit/billing';

const provider = BillingProviderSchema.parse(
  process.env.NEXT_PUBLIC_BILLING_PROVIDER,
);

export default createBillingSchema({
  provider,
  products: [
    {
      id: 'free',
      name: 'Free',
      description: 'For experimenting with agent reliability',
      currency: 'USD',
      hidden: true,
      plans: [],
      features: [
        '10,000 observations/mo',
        '500 verifications/mo',
        '3 agents',
        '1 seat',
        '7-day retention',
        'Community support',
      ],
    },
    {
      id: 'pro',
      name: 'Pro',
      badge: 'Most Popular',
      highlighted: true,
      description: 'For teams shipping agents to production',
      currency: 'USD',
      plans: [
        {
          name: 'Pro Monthly',
          id: 'pro-monthly',
          paymentType: 'recurring',
          interval: 'month',
          lineItems: [
            {
              id: 'price_vex_pro_monthly',
              name: 'Pro',
              cost: 79,
              type: 'flat',
            },
          ],
        },
        {
          name: 'Pro Yearly',
          id: 'pro-yearly',
          paymentType: 'recurring',
          interval: 'year',
          lineItems: [
            {
              id: 'price_vex_pro_yearly',
              name: 'Pro',
              cost: 790,
              type: 'flat',
            },
          ],
        },
      ],
      features: [
        '100,000 observations/mo',
        '10,000 verifications/mo',
        '15 agents',
        '5 seats',
        '30-day retention',
        'Full correction cascade',
        'Email + webhook alerts',
        'Email support (48h SLA)',
      ],
    },
    {
      id: 'team',
      name: 'Team',
      description: 'For scaling teams with mission-critical agents',
      currency: 'USD',
      plans: [
        {
          name: 'Team Monthly',
          id: 'team-monthly',
          paymentType: 'recurring',
          interval: 'month',
          lineItems: [
            {
              id: 'price_vex_team_monthly',
              name: 'Team',
              cost: 299,
              type: 'flat',
            },
          ],
        },
        {
          name: 'Team Yearly',
          id: 'team-yearly',
          paymentType: 'recurring',
          interval: 'year',
          lineItems: [
            {
              id: 'price_vex_team_yearly',
              name: 'Team',
              cost: 2990,
              type: 'flat',
            },
          ],
        },
      ],
      features: [
        '1,000,000 observations/mo',
        '100,000 verifications/mo',
        'Unlimited agents',
        '15 seats',
        '90-day retention',
        'Full correction cascade + priority',
        'Email + webhook + Slack alerts',
        'Priority support (24h SLA)',
      ],
    },
  ],
});
```

**Step 2: Verify build**

Run: `cd apps/web && pnpm build` (or `pnpm typecheck` if full build isn't needed)
Expected: No type errors. The billing schema validates successfully.

**Step 3: Commit**

```bash
git add apps/web/config/billing.config.ts
git commit -m "feat: replace placeholder billing config with Vex pricing tiers"
```

---

### Task 3: Plan Limits Configuration (Shared Constants)

**Files:**
- Create: `services/shared/shared/plan_limits.py`

**Context:** Both the ingestion API and sync gateway need to know plan limits. Define them once in the shared package.

**Step 1: Create plan_limits.py**

Create `services/shared/shared/plan_limits.py`:

```python
"""Plan-level limits for Vex pricing tiers.

These constants define the quotas, rate limits, and feature flags
for each plan. The ``PLAN_LIMITS`` dict is keyed by the ``plan``
column value in the ``organizations`` table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class PlanConfig:
    """Immutable configuration for a single pricing plan."""

    # Monthly quotas
    observations_per_month: int
    verifications_per_month: int

    # Rate limit (overrides per-key RPM if lower)
    max_rpm: int

    # Resource limits
    max_agents: int
    max_seats: int

    # Feature flags
    corrections_enabled: bool
    webhook_alerts: bool
    slack_alerts: bool

    # Data retention (days)
    retention_days: int

    # Overage: if True, requests beyond quota are allowed (billed).
    # If False, requests beyond quota are rejected (429).
    overage_allowed: bool


PLAN_LIMITS: Dict[str, PlanConfig] = {
    "free": PlanConfig(
        observations_per_month=10_000,
        verifications_per_month=500,
        max_rpm=100,
        max_agents=3,
        max_seats=1,
        corrections_enabled=False,
        webhook_alerts=False,
        slack_alerts=False,
        retention_days=7,
        overage_allowed=False,
    ),
    "pro": PlanConfig(
        observations_per_month=100_000,
        verifications_per_month=10_000,
        max_rpm=1_000,
        max_agents=15,
        max_seats=5,
        corrections_enabled=True,
        webhook_alerts=True,
        slack_alerts=False,
        retention_days=30,
        overage_allowed=True,
    ),
    "team": PlanConfig(
        observations_per_month=1_000_000,
        verifications_per_month=100_000,
        max_rpm=5_000,
        max_agents=-1,  # unlimited
        max_seats=15,
        corrections_enabled=True,
        webhook_alerts=True,
        slack_alerts=True,
        retention_days=90,
        overage_allowed=True,
    ),
}


def get_plan_config(plan: str) -> PlanConfig:
    """Return the PlanConfig for the given plan name.

    Falls back to ``"free"`` for unknown plan values.
    """
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
```

**Step 2: Commit**

```bash
git add services/shared/shared/plan_limits.py
git commit -m "feat: add plan limits configuration for Free/Pro/Team tiers"
```

---

### Task 4: Extend KeyValidator with Plan-Aware Quota Enforcement

**Files:**
- Modify: `services/shared/shared/auth.py`

**Context:** The `KeyValidator._query_db()` currently only fetches `org_id` and `api_keys`. We need to also fetch `plan`, then add a `_check_quota()` method that counts the org's usage this billing period and rejects if over quota (Free) or flags for overage billing (Pro/Team).

**Step 1: Update `_CachedKey` to include plan**

In `services/shared/shared/auth.py`, add `plan: str` to the `_CachedKey` dataclass (after `revoked`):

```python
@dataclass
class _CachedKey:
    """Internal cached representation of a validated key."""
    org_id: str
    key_id: str
    scopes: List[str]
    rate_limit_rpm: int
    expires_at: Optional[datetime]
    revoked: bool
    plan: str = "free"
    cached_at: float = field(default_factory=time.monotonic)
```

Also add `plan: str` to `KeyInfo`:

```python
@dataclass
class KeyInfo:
    """Validated API key information returned to the caller."""
    org_id: str
    key_id: str
    scopes: List[str]
    plan: str = "free"
```

**Step 2: Update `_query_db()` to fetch plan**

Change the SQL query to also select `plan`:

```python
result = conn.execute(
    text(
        """
        SELECT org_id, api_keys, plan
        FROM organizations
        WHERE api_keys @> CAST(:filter AS jsonb)
        """
    ),
    {"filter": json.dumps([{"key_hash": key_hash}])},
)
```

And when constructing `_CachedKey`, add:
```python
plan=row[2] if row[2] else "free",
```

**Step 3: Override per-key RPM with plan max**

In `_query_db()`, after reading `rate_limit_rpm` from the key entry, cap it at the plan's `max_rpm`:

```python
from shared.plan_limits import get_plan_config

# Inside _query_db, after building _CachedKey:
plan_config = get_plan_config(row[2] if row[2] else "free")
per_key_rpm = key_entry.get("rate_limit_rpm", 1000)
effective_rpm = min(per_key_rpm, plan_config.max_rpm)
```

Use `effective_rpm` as the `rate_limit_rpm` value in `_CachedKey`.

**Step 4: Add `_check_quota()` method**

Add a new method to `KeyValidator`:

```python
def _check_quota(self, entry: _CachedKey) -> None:
    """Enforce monthly quota based on organization plan."""
    plan_config = get_plan_config(entry.plan)

    # Determine quota based on service scope
    if self._required_scope == "verify":
        monthly_limit = plan_config.verifications_per_month
    else:
        monthly_limit = plan_config.observations_per_month

    # Query current month usage from executions continuous aggregate
    try:
        with self._engine.connect() as conn:
            result = conn.execute(
                text(
                    """
                    SELECT COALESCE(SUM(execution_count), 0)
                    FROM hourly_agent_stats
                    WHERE org_id = :org_id
                      AND bucket >= date_trunc('month', NOW())
                    """
                ),
                {"org_id": entry.org_id},
            )
            current_usage = result.scalar() or 0
    except Exception:
        logger.warning("Failed to check quota, allowing request", exc_info=True)
        return  # fail open — don't block on quota check errors

    if current_usage >= monthly_limit:
        if not plan_config.overage_allowed:
            raise AuthError(
                429,
                f"Monthly quota exceeded ({current_usage}/{monthly_limit}). "
                f"Upgrade your plan at https://app.tryvex.dev",
                retry_after_seconds=3600,
            )
        # For paid plans: allow but log for overage billing
        logger.info(
            "Overage: org=%s plan=%s usage=%d limit=%d",
            entry.org_id, entry.plan, current_usage, monthly_limit,
        )
```

**Step 5: Call `_check_quota()` in `validate()`**

In the `validate()` method, add quota check after rate limit check (step 6), before usage tracking (step 7):

```python
# 6. Check rate limit
self._check_rate_limit(entry)

# 6b. Check monthly quota
self._check_quota(entry)

# 7. Track usage (batched)
self._track_usage(entry.key_id)
```

**Step 6: Update `validate()` return to include plan**

```python
return KeyInfo(
    org_id=entry.org_id,
    key_id=entry.key_id,
    scopes=entry.scopes,
    plan=entry.plan,
)
```

**Step 7: Verify**

Run: `cd services && python -c "from shared.auth import KeyValidator; print('OK')"`
Expected: Import succeeds without errors.

**Step 8: Commit**

```bash
git add services/shared/shared/auth.py
git commit -m "feat: add plan-aware quota enforcement to KeyValidator"
```

---

### Task 5: Feature Gate — Block Corrections on Free Plan

**Files:**
- Modify: `services/sync-gateway/app/routes.py`

**Context:** The sync gateway's `/v1/verify` endpoint runs the verification engine. When the verification engine returns a `block` action, it triggers the correction cascade. On the Free plan, corrections should be disabled — the response should include the verification result but skip correction.

**Step 1: Read the current verify route**

Read `services/sync-gateway/app/routes.py` to understand how the verify endpoint works and where the correction cascade is triggered.

**Step 2: Add plan check before correction**

After the `KeyValidator.validate()` call returns `KeyInfo`, check `key_info.plan`:

```python
from shared.plan_limits import get_plan_config

# In the verify route, after getting verification result:
plan_config = get_plan_config(key_info.plan)
if not plan_config.corrections_enabled:
    # Skip correction, return verification result as-is
    result["correction_skipped"] = True
    result["correction_skipped_reason"] = "upgrade_required"
```

The exact integration point depends on the current code structure — read the file first.

**Step 3: Commit**

```bash
git add services/sync-gateway/app/routes.py
git commit -m "feat: gate correction cascade behind paid plan check"
```

---

### Task 6: Dashboard Usage Meter Component

**Files:**
- Create: `apps/web/app/home/[account]/_components/usage-meter.tsx`

**Context:** The dashboard should show current billing period usage vs. plan limits. This is a server component that queries the AgentGuard API for usage stats.

**Step 1: Create usage-meter component**

Create `apps/web/app/home/[account]/_components/usage-meter.tsx`:

```tsx
import { Trans } from '@kit/ui/trans';

interface UsageMeterProps {
  label: string;
  current: number;
  limit: number;
  unit?: string;
}

export function UsageMeter({ label, current, limit, unit = '' }: UsageMeterProps) {
  const percentage = limit > 0 ? Math.min((current / limit) * 100, 100) : 0;
  const isWarning = percentage >= 80;
  const isExceeded = percentage >= 100;

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium">{label}</span>
        <span className="text-sm text-muted-foreground">
          {current.toLocaleString()} / {limit.toLocaleString()} {unit}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-muted">
        <div
          className={`h-full rounded-full transition-all ${
            isExceeded
              ? 'bg-destructive'
              : isWarning
                ? 'bg-warning'
                : 'bg-primary'
          }`}
          style={{ width: `${percentage}%` }}
        />
      </div>
      {isExceeded && (
        <p className="mt-2 text-xs text-destructive">
          Quota exceeded. Upgrade your plan for uninterrupted service.
        </p>
      )}
      {isWarning && !isExceeded && (
        <p className="mt-2 text-xs text-warning">
          Approaching limit ({Math.round(percentage)}% used).
        </p>
      )}
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add apps/web/app/home/[account]/_components/usage-meter.tsx
git commit -m "feat: add usage meter component for plan quota display"
```

---

### Task 7: Dashboard Usage Overview Section

**Files:**
- Modify: `apps/web/app/home/[account]/page.tsx` (or the dashboard homepage)

**Context:** Add a usage overview section to the team account dashboard that shows observation and verification usage meters for the current billing period, plus a link to the billing page.

**Step 1: Read the current dashboard page**

Read `apps/web/app/home/[account]/page.tsx` to understand the current layout.

**Step 2: Add usage meters**

Import the `UsageMeter` component and add a section that:
1. Fetches current month usage from the AgentGuard API (observations + verifications count)
2. Determines plan limits from the org's plan
3. Renders two `UsageMeter` components (observations + verifications)
4. Shows an upgrade CTA if on Free plan

The exact implementation depends on how the dashboard currently fetches data — read the file first to match existing patterns.

**Step 3: Commit**

```bash
git add apps/web/app/home/[account]/page.tsx
git commit -m "feat: add usage overview with plan meters to dashboard"
```

---

### Task 8: Data Retention Enforcement Migration

**Files:**
- Create: `services/migrations/alembic/versions/NNN_add_retention_policy.py`

**Context:** TimescaleDB supports automatic data retention via `add_retention_policy()`. We need to set up retention based on the plan's retention_days. Since retention is per-org and plans can change, the simplest approach is a scheduled job that deletes data older than the org's plan allows.

**Step 1: Create migration**

Create a new Alembic migration that adds a PostgreSQL function and a scheduled job (via pg_cron or a Python worker) to enforce retention:

```python
"""Add plan-based data retention enforcement.

Revision ID: NNN
"""

from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    # Create a function that deletes expired data per-org based on plan
    op.execute("""
        CREATE OR REPLACE FUNCTION enforce_plan_retention()
        RETURNS void AS $$
        DECLARE
            org RECORD;
            retention_days INT;
        BEGIN
            FOR org IN SELECT org_id, plan FROM organizations LOOP
                retention_days := CASE org.plan
                    WHEN 'team' THEN 90
                    WHEN 'pro' THEN 30
                    ELSE 7
                END;

                DELETE FROM executions
                WHERE org_id = org.org_id
                  AND timestamp < NOW() - (retention_days || ' days')::INTERVAL;

                DELETE FROM check_results
                WHERE execution_id IN (
                    SELECT execution_id FROM executions
                    WHERE org_id = org.org_id
                      AND timestamp < NOW() - (retention_days || ' days')::INTERVAL
                );
            END LOOP;
        END;
        $$ LANGUAGE plpgsql;
    """)

def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS enforce_plan_retention();")
```

**Note:** The actual scheduling (pg_cron or external cron) depends on the deployment setup. The function should run daily.

**Step 2: Commit**

```bash
git add services/migrations/alembic/versions/
git commit -m "feat: add plan-based data retention enforcement function"
```

---

### Task 9: Seat and Agent Limit Enforcement (Dashboard)

**Files:**
- Modify: Team member invite flow (find the invite action in `apps/web/`)
- Modify: Agent creation flow (find in `apps/web/`)

**Context:** When a user tries to invite a team member or create a new agent, check against the plan's `max_seats` and `max_agents` limits. Reject with an upgrade message if at limit.

**Step 1: Find the invite and agent creation flows**

Search for team member invite handling and agent creation in the dashboard codebase. These are likely server actions.

**Step 2: Add plan limit checks**

Before creating a new agent or inviting a member:
1. Query the org's current plan
2. Count existing agents/members
3. Compare against `PlanConfig.max_agents` / `PlanConfig.max_seats`
4. Return an error with upgrade messaging if at limit

The exact implementation depends on the existing code — read the files first.

**Step 3: Commit**

```bash
git commit -m "feat: enforce seat and agent limits based on plan tier"
```

---

### Task 10: Update Landing Site Nav, Sitemap, and SEO

**Files:**
- Modify: `apps/landing/app/_components/site-footer.tsx` (add pricing link)
- Modify: `apps/landing/app/blog/[slug]/page.tsx` (add pricing CTA)

**Step 1: Add Pricing to footer**

Add a "Pricing" link to the footer's product section.

**Step 2: Update blog post CTA**

In the `PostCta` component, update the copy to mention the free tier.

**Step 3: Commit**

```bash
git add apps/landing/
git commit -m "feat: add pricing links to footer and blog CTAs"
```

---

## Task Dependencies

```
Task 1 (Pricing Page)     — independent, can start immediately
Task 2 (Billing Config)   — independent, can start immediately
Task 3 (Plan Limits)      — independent, can start immediately
Task 4 (Quota Enforcement) — depends on Task 3
Task 5 (Correction Gate)  — depends on Task 3
Task 6 (Usage Meter)      — independent
Task 7 (Dashboard Usage)  — depends on Task 6
Task 8 (Retention)        — independent
Task 9 (Seat/Agent Limits) — depends on Task 3
Task 10 (Nav/SEO)         — depends on Task 1
```

## Parallel Execution Groups

- **Group A (Landing):** Tasks 1, 10
- **Group B (Backend):** Tasks 3 → 4 → 5
- **Group C (Dashboard):** Tasks 2, 6 → 7, 9
- **Group D (Infra):** Task 8
