# Vex Monetization Design

## Overview

Platform fee + usage-based pricing with 3 tiers (Free / Pro / Team), generous overage on paid plans, and cloud-only delivery. Targeting startups and small teams (5-50 people) with AI agents in production.

## Pricing Tiers

| | Free | Pro ($79/mo, $790/yr) | Team ($299/mo, $2,990/yr) |
|---|---|---|---|
| **Observations/mo** | 10,000 | 100,000 | 1,000,000 |
| **Verifications/mo** | 500 | 10,000 | 100,000 |
| **Corrections** | None | Full 3-layer cascade | Full cascade + priority |
| **Agents** | 3 | 15 | Unlimited |
| **Seats** | 1 | 5 | 15 |
| **Data retention** | 7 days | 30 days | 90 days |
| **Overage (observe)** | Hard limit | $0.0005/obs | $0.0004/obs |
| **Overage (verify)** | Hard limit | $0.005/verify | $0.004/verify |
| **API rate limit** | 100 RPM | 1,000 RPM | 5,000 RPM |
| **Alerts** | Email only | Email + webhook | Email + webhook + Slack |
| **Support** | Community (GitHub) | Email (48h SLA) | Priority (24h SLA) |
| **Yearly discount** | — | ~20% (save $158) | ~20% (save $598) |

## Unit Economics

### Cost Per Operation

| Operation | Our cost | Notes |
|---|---|---|
| Observe (async ingest) | ~$0.00001 | Redis + DB + S3 write |
| Verify (sync, LLM calls) | ~$0.002 | Tiered LLM: Haiku/Flash first, GPT-4o escalation ~20% of calls |
| Correct (cascade, ~10% rate) | ~$0.003 per correction, ~$0.0003 amortized | Most stop at layer 1 |

### Margin Analysis

| Plan | Revenue/mo | Observe cost (full) | Verify cost (full) | Gross margin |
|---|---|---|---|---|
| Free | $0 | $0.10 | $1.00 | -$1.10 (loss leader) |
| Pro | $79 | $1.00 | $20.00 | ~73% ($58) |
| Team | $299 | $10.00 | $200.00 | ~30% ($89) |

At typical usage (~40-50% of limits): Pro ~85% margin, Team ~70% margin.

### Competitive Positioning

- **LangSmith Plus**: $39/seat/mo + $0.50/1K traces. 5-seat team = $195/mo for observability only.
- **Langfuse Pro**: Usage-based from $0 for 100K observations. No verification/correction.
- **Vex Pro**: $79/mo for 5 seats + 100K observations + 10K verifications + corrections. More value, competitive price.

Key differentiator: Vex is the only product that verifies and corrects in real-time. LangSmith/Langfuse only observe.

## Implementation Scope

### 1. Pricing Page (Landing site)

- New `/pricing` route at `apps/landing/app/pricing/page.tsx`
- 3-column plan comparison with full feature matrix
- Monthly/yearly toggle
- CTAs: "Get Started Free" / "Start Pro" / "Contact Sales"
- FAQ section
- Add "Pricing" to site header nav

### 2. Stripe Configuration

- Create Stripe Products: Pro Monthly, Pro Yearly, Team Monthly, Team Yearly
- Configure metered billing components for overage (observation + verification separately)
- Update `apps/web/config/billing.config.ts` with real Stripe price IDs
- Map plan features to billing config

### 3. Backend Enforcement

- **Quota tracking**: Count observations + verifications per org per billing period using existing TimescaleDB aggregates
- **Rate limiting**: Enforce RPM limits per API key based on org plan (gateway middleware)
- **Feature gating**: Block correction cascade on Free tier (verification engine check)
- **Overage metering**: Report usage to Stripe metered billing API at end of period
- **Hard limits on Free**: Reject requests beyond quota with 429 + upgrade prompt

### 4. Dashboard Updates

- **Usage meter widget**: Show current period observations/verifications vs. limits with progress bars
- **Upgrade prompts**: Banner when >80% of quota used, modal when quota exhausted
- **Billing page**: Replace Makerkit placeholder plans with Vex-specific plan display

### 5. Plan-Gated Features

- **Retention enforcement**: Cron job to delete data older than plan retention limit
- **Seat limits**: Enforce max team members per plan on invite
- **Agent limits**: Enforce max agents per plan on agent creation
- **Alert channel gating**: Webhook/Slack integration only on paid plans

## Decisions Made

- **Platform fee + usage** over pure usage-based: predictable revenue, budget-friendly for startups
- **Free tier (forever)** over free trial: growth engine for developer tools
- **Cloud-only for now**: no self-hosted option until enterprise demand materializes
- **3 tiers** over 4: simpler pricing page, matches existing Makerkit billing infra
- **Separate observe/verify quotas**: reflects real cost structure, lets free users observe freely while gating expensive verification
- **Generous overage on paid plans**: no hard cutoffs, automatic billing, reduces churn from quota exhaustion

## Sources

- [LangSmith Pricing](https://www.langchain.com/pricing)
- [Langfuse Pricing](https://langfuse.com/pricing)
