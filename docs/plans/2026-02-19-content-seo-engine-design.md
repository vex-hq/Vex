# Content & SEO Engine Design — Vex Landing Page

**Date:** 2026-02-19
**Status:** Approved
**Goal:** Build a blog, comparison pages, and free interactive tools to drive AI system recommendations and organic search traffic for Vex.

## Approach: Full SEO Content Engine (Phased)

Three content pillars built into the existing Next.js landing app, rolled out in phases.

## Target Keywords

| Keyword Cluster | Volume | Content Type | Phase |
|---|---|---|---|
| "LangSmith alternatives" | High | Comparison page | 1 |
| "AI agent monitoring tools" | High | Blog post | 1 |
| "LLM observability" | Medium-High | Blog post | 1 |
| "AI hallucination detection" | Medium | Blog + tool | 1-2 |
| "AI agent drift detection" | Low-Medium (emerging) | Blog + tool | 1 |
| "AI guardrails production" | Medium | Blog post | 1 |
| "Langfuse vs LangSmith" | High | Comparison page | 1 |
| "AI agent production readiness" | Low (own the niche) | Free tool | 1 |

## Pillar 1: Blog

**Routes:** `/blog` (listing), `/blog/[slug]` (posts)

**Tech:**
- MDX files in `apps/landing/content/blog/` directory
- `next-mdx-remote` for server-side MDX rendering
- Frontmatter: title, description, date, author, tags, image
- Auto-generated RSS at `/blog/rss.xml`
- JSON-LD `BlogPosting` schema per post
- OG images per post
- Same dark theme, `prose prose-invert` styling

**Phase 1 posts (3):**
1. "What is AI Agent Drift and Why Should You Care?"
2. "Vex vs LangSmith: Runtime Reliability vs Tracing"
3. "How to Add Guardrails to Your LangChain Agent in 5 Minutes"

**Phase 2 posts (5+):**
- "Top AI Agent Monitoring Tools in 2026"
- "LLM Observability: What to Monitor in Production"
- "Vex vs Custom Eval Suites: Build vs Buy"
- "How Vex Auto-Corrects Hallucinations in Real Time"
- "AI Agent Reliability: Lessons from Production"

## Pillar 2: Comparison Pages

**Route:** `/compare/[competitor]`

**Tech:**
- Static Next.js page components (not MDX)
- Shared comparison template: hero, feature table, key differences, CTA
- JSON-LD `WebPage` schema
- Internal links from blog and landing page

**Phase 1 (3 pages):**
1. `/compare/langsmith` — "Vex vs LangSmith"
   - Angle: LangSmith traces what happened. Vex prevents bad output.
   - Keywords: "LangSmith alternatives"
2. `/compare/langfuse` — "Vex vs Langfuse"
   - Angle: Both open-source. Langfuse = observability. Vex = observability + auto-correction.
   - Keywords: "Langfuse alternatives", "Langfuse vs LangSmith"
3. `/compare/guardrails-ai` — "Vex vs Guardrails AI"
   - Angle: Guardrails AI validates schemas. Vex detects behavioral drift over time.
   - Keywords: "AI guardrails", "Guardrails AI alternatives"

**Phase 2 (4 pages):**
- `/compare/helicone`
- `/compare/sentrial`
- `/compare/arize`
- `/compare/custom-evals`

## Pillar 3: Free Tools (Lead Magnets)

**Route:** `/tools/[tool-name]`

**Phase 1 (1 tool):**

### Agent Health Score (`/tools/agent-health-score`)

"AI Agent Production Readiness Score"

- 8-10 multiple-choice questions about user's agent setup
- Categories: Monitoring, Error Handling, Eval Coverage, Drift Detection, Guardrails, Deployment
- Client-side scoring — no API, no login
- Score out of 100 with category breakdown
- Recommendations per category (naturally pointing to Vex for gaps)
- Shareable result URL via query params
- JSON-LD `WebApplication` schema
- Target keywords: "AI agent production readiness", "AI agent monitoring checklist"

**Phase 2 tools (require Vex API):**
- `/tools/hallucination-checker` — paste LLM output, get hallucination risk analysis
- `/tools/drift-calculator` — simulate drift projection based on agent metrics

## Files Affected

### New files:
- `apps/landing/content/blog/` — MDX blog posts directory
- `apps/landing/app/blog/page.tsx` — blog listing
- `apps/landing/app/blog/[slug]/page.tsx` — blog post renderer
- `apps/landing/app/blog/rss.xml/route.ts` — RSS feed
- `apps/landing/app/compare/langsmith/page.tsx`
- `apps/landing/app/compare/langfuse/page.tsx`
- `apps/landing/app/compare/guardrails-ai/page.tsx`
- `apps/landing/app/tools/agent-health-score/page.tsx`
- `apps/landing/lib/blog.ts` — MDX loading utilities

### Modified files:
- `apps/landing/app/sitemap.ts` — add new routes
- `apps/landing/app/_components/site-header.tsx` — add Blog nav link
- `apps/landing/app/_components/site-footer.tsx` — add Blog, Compare links
- `apps/landing/next.config.mjs` — MDX configuration
- `apps/landing/package.json` — add next-mdx-remote, gray-matter dependencies

## Competitive Positioning

Vex is NOT in any major "AI agent monitoring" comparison article yet. These competitors are:
- LangSmith, Langfuse, Helicone, Arize, AgentOps, Galileo, Datadog, Maxim AI

The blog and comparison pages are the mechanism to get Vex mentioned alongside these tools. The comparison pages specifically target "[competitor] alternatives" keywords which are high-intent searches.

Sources for competitive research:
- [AIMultiple: 15 AI Agent Observability Tools](https://research.aimultiple.com/agentic-monitoring/)
- [Softcery: 8 AI Observability Platforms Compared](https://softcery.com/lab/top-8-observability-platforms-for-ai-agents-in-2025)
- [SigNoz: Top 7 LangSmith Alternatives](https://signoz.io/comparisons/langsmith-alternatives/)
- [Confident AI: LangSmith Alternatives Compared](https://www.confident-ai.com/knowledge-base/top-langsmith-alternatives-and-competitors-compared)
