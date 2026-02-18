# Content & SEO Engine Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a blog (MDX), 3 comparison pages, 3 blog posts, and 1 free interactive tool into the Vex landing page to drive organic search traffic and AI system recommendations.

**Architecture:** All content lives in `apps/landing/`. Blog posts are MDX files in `content/blog/`, loaded via `next-mdx-remote` and `gray-matter`. Comparison pages and the tool are static Next.js page components. Everything shares the existing dark theme and layout.

**Tech Stack:** Next.js App Router, TypeScript, Tailwind CSS 4, next-mdx-remote, gray-matter

**Working directory:** `/Users/thakurg/Hive/Research/AgentGuard/nextjs-application`

---

### Task 1: Install blog dependencies

**Files:**
- Modify: `apps/landing/package.json`

**Step 1: Install packages**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard/nextjs-application
pnpm --filter landing add next-mdx-remote gray-matter reading-time
```

**Step 2: Verify install**

Run: `pnpm --filter landing build`
Expected: Build succeeds.

**Step 3: Commit**

```bash
git add apps/landing/package.json pnpm-lock.yaml
git commit -m "feat(landing): add blog dependencies (next-mdx-remote, gray-matter, reading-time)"
```

---

### Task 2: Create blog utility library

**Files:**
- Create: `apps/landing/lib/blog.ts`

**Step 1: Create the utility**

```typescript
import fs from 'fs';
import path from 'path';

import matter from 'gray-matter';

const BLOG_DIR = path.join(process.cwd(), 'content', 'blog');

export interface BlogPost {
  slug: string;
  title: string;
  description: string;
  date: string;
  author: string;
  tags: string[];
  image?: string;
  content: string;
}

export function getAllPosts(): BlogPost[] {
  if (!fs.existsSync(BLOG_DIR)) return [];

  const files = fs.readdirSync(BLOG_DIR).filter((f) => f.endsWith('.mdx'));

  const posts = files.map((filename) => {
    const slug = filename.replace('.mdx', '');
    const filePath = path.join(BLOG_DIR, filename);
    const fileContent = fs.readFileSync(filePath, 'utf-8');
    const { data, content } = matter(fileContent);

    return {
      slug,
      title: data.title ?? '',
      description: data.description ?? '',
      date: data.date ?? '',
      author: data.author ?? 'Vex Team',
      tags: data.tags ?? [],
      image: data.image,
      content,
    };
  });

  return posts.sort(
    (a, b) => new Date(b.date).getTime() - new Date(a.date).getTime(),
  );
}

export function getPostBySlug(slug: string): BlogPost | undefined {
  const posts = getAllPosts();
  return posts.find((p) => p.slug === slug);
}
```

**Step 2: Build and verify**

Run: `pnpm --filter landing build`
Expected: Build succeeds.

**Step 3: Commit**

```bash
git add apps/landing/lib/blog.ts
git commit -m "feat(landing): add blog utility library"
```

---

### Task 3: Create blog listing page

**Files:**
- Create: `apps/landing/app/blog/page.tsx`

**Step 1: Create the page**

```tsx
import type { Metadata } from 'next';
import Link from 'next/link';

import { getAllPosts } from '~/lib/blog';

export const metadata: Metadata = {
  title: 'Blog — Vex',
  description:
    'Insights on AI agent monitoring, runtime reliability, drift detection, and production guardrails.',
};

export default function BlogPage() {
  const posts = getAllPosts();

  return (
    <div className="container py-24">
      <div className="mb-4 text-[13px] font-medium uppercase tracking-widest text-emerald-500">
        Blog
      </div>
      <h1 className="mb-12 text-3xl font-bold text-white sm:text-4xl">
        Insights & Guides
      </h1>

      {posts.length === 0 ? (
        <p className="text-[#a2a2a2]">No posts yet. Check back soon.</p>
      ) : (
        <div className="grid gap-8 md:grid-cols-2 lg:grid-cols-3">
          {posts.map((post) => (
            <Link
              key={post.slug}
              href={`/blog/${post.slug}`}
              className="group rounded-xl border border-[#252525] bg-[#0a0a0a] p-6 transition-colors hover:border-[#585858] hover:bg-[#161616]"
            >
              <div className="mb-3 flex items-center gap-2">
                <time className="text-xs text-[#585858]">{post.date}</time>
                {post.tags.slice(0, 2).map((tag) => (
                  <span
                    key={tag}
                    className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-500"
                  >
                    {tag}
                  </span>
                ))}
              </div>
              <h2 className="mb-2 text-lg font-semibold text-white group-hover:text-emerald-400">
                {post.title}
              </h2>
              <p className="text-sm leading-relaxed text-[#a2a2a2]">
                {post.description}
              </p>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
```

**Step 2: Build and verify**

Run: `pnpm --filter landing build`
Expected: Build succeeds. `/blog` route appears.

**Step 3: Commit**

```bash
git add apps/landing/app/blog/page.tsx
git commit -m "feat(landing): add blog listing page"
```

---

### Task 4: Create blog post renderer

**Files:**
- Create: `apps/landing/app/blog/[slug]/page.tsx`

**Step 1: Create the page**

```tsx
import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { MDXRemote } from 'next-mdx-remote/rsc';

import { getAllPosts, getPostBySlug } from '~/lib/blog';

interface Props {
  params: Promise<{ slug: string }>;
}

export async function generateStaticParams() {
  const posts = getAllPosts();
  return posts.map((post) => ({ slug: post.slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const post = getPostBySlug(slug);
  if (!post) return {};

  return {
    title: `${post.title} — Vex Blog`,
    description: post.description,
    openGraph: {
      title: post.title,
      description: post.description,
      type: 'article',
      publishedTime: post.date,
    },
  };
}

export default async function BlogPostPage({ params }: Props) {
  const { slug } = await params;
  const post = getPostBySlug(slug);
  if (!post) notFound();

  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'BlogPosting',
    headline: post.title,
    description: post.description,
    datePublished: post.date,
    author: {
      '@type': 'Organization',
      name: 'Vex',
    },
    publisher: {
      '@type': 'Organization',
      name: 'Vex',
      url: 'https://tryvex.dev',
    },
  };

  return (
    <div className="container py-24">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      <article className="mx-auto max-w-[720px]">
        <div className="mb-8">
          <div className="mb-4 flex items-center gap-3">
            <time className="text-sm text-[#585858]">{post.date}</time>
            {post.tags.map((tag) => (
              <span
                key={tag}
                className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-500"
              >
                {tag}
              </span>
            ))}
          </div>
          <h1 className="text-3xl font-bold leading-tight text-white sm:text-4xl">
            {post.title}
          </h1>
          <p className="mt-4 text-lg text-[#a2a2a2]">{post.description}</p>
        </div>

        <div className="prose prose-invert max-w-none text-[#a2a2a2] prose-headings:text-white prose-headings:font-semibold prose-h2:text-xl prose-h2:mt-10 prose-h2:mb-4 prose-h3:text-lg prose-h3:mt-8 prose-h3:mb-3 prose-p:leading-relaxed prose-p:text-[#a2a2a2] prose-li:text-[#a2a2a2] prose-strong:text-white prose-a:text-emerald-500 hover:prose-a:text-emerald-400 prose-code:text-emerald-400 prose-code:bg-[#161616] prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:text-sm prose-pre:bg-[#161616] prose-pre:border prose-pre:border-[#252525]">
          <MDXRemote source={post.content} />
        </div>
      </article>
    </div>
  );
}
```

**Step 2: Build and verify**

Run: `pnpm --filter landing build`
Expected: Build succeeds. (No posts yet, so no dynamic routes generated.)

**Step 3: Commit**

```bash
git add apps/landing/app/blog/\[slug\]/page.tsx
git commit -m "feat(landing): add blog post renderer with MDX support"
```

---

### Task 5: Write first blog post — "What is AI Agent Drift"

**Files:**
- Create: `apps/landing/content/blog/what-is-ai-agent-drift.mdx`

**Step 1: Create the content directory and post**

```bash
mkdir -p apps/landing/content/blog
```

Create `apps/landing/content/blog/what-is-ai-agent-drift.mdx`:

```mdx
---
title: "What is AI Agent Drift and Why Should You Care?"
description: "AI agents pass evals, ship to production, then slowly change behavior. Learn what drift is, why it happens, and how to detect it before your users do."
date: "2026-02-19"
author: "Vex Team"
tags: ["drift detection", "production"]
---

## The Silent Failure Mode

Your AI agent passed every eval. It shipped to production. Users were happy. Then, three weeks later, support tickets start appearing. The agent isn't wrong exactly — it's just... different. Responses are shorter. It skips steps it used to complete. It confidently states things that aren't quite true.

This is **agent drift** — the gradual, undetected change in an AI agent's behavior over time in production.

## Why Agents Drift

Drift happens for several reasons, and none of them trigger traditional error monitoring:

### 1. Model Updates

When your LLM provider ships a new model version (even minor ones), your agent's behavior changes. The same prompt produces subtly different outputs. Your evals might still pass, but the distribution of responses has shifted.

### 2. Context Window Pollution

As agents accumulate conversation history, tool outputs, and retrieval results, the effective context changes. What worked with a clean context degrades as real-world data introduces noise.

### 3. Data Distribution Shift

The inputs your agent sees in production are never identical to your eval dataset. Real users ask questions you didn't anticipate, use phrasing you didn't test, and combine features in ways you didn't consider.

### 4. Compounding Errors in Multi-Agent Systems

In multi-agent pipelines, a small drift in Agent A's output becomes a larger drift in Agent B's input, which cascades through the entire workflow. A 2% drift at each step becomes a 10% drift by the end.

## The Cost of Undetected Drift

Traditional monitoring won't catch drift because:

- **No errors are thrown** — the agent responds successfully
- **Latency stays normal** — performance metrics look fine
- **Logs show nothing unusual** — every request completes

The only signal is behavioral: the agent's outputs have changed in ways that matter to your users but don't register in your monitoring stack.

Companies typically discover drift through:
- Customer complaints (hours to days after drift begins)
- Manual spot-checks (if you're lucky enough to do them)
- Downstream metric drops (revenue, NPS, task completion rates)

## How to Detect Drift

Effective drift detection requires monitoring the **distribution of agent behaviors**, not just individual outputs:

1. **Baseline your agent** — Record the distribution of outputs, tool usage patterns, and decision paths during a known-good period
2. **Monitor continuously** — Compare live behavior against the baseline in real-time
3. **Set semantic thresholds** — Flag when behavior deviates beyond acceptable bounds
4. **Auto-correct when possible** — Block or rewrite drifted outputs before they reach users

## What Vex Does

[Vex](https://tryvex.dev) is an open-source runtime reliability layer that automates all four steps. You wrap your agent function with the Vex SDK, and it:

- **Observes** every LLM call, tool use, and decision
- **Detects** drift by comparing against learned behavioral baselines
- **Corrects** hallucinations and policy violations in real-time
- **Optimizes** prompts and thresholds from failure patterns

```python
from vex_sdk import guard

@guard.watch()
def my_agent(input: str) -> str:
    # your agent logic
    return response
```

Three lines. Five minutes to set up. Start catching drift from the first request.

---

*Ready to stop drift before your users notice? [Get started with Vex](https://tryvex.dev) — it's free and open source.*
```

**Step 2: Build and verify**

Run: `pnpm --filter landing build`
Expected: Build succeeds. `/blog/what-is-ai-agent-drift` route appears.

**Step 3: Commit**

```bash
git add apps/landing/content/blog/what-is-ai-agent-drift.mdx
git commit -m "content(blog): add 'What is AI Agent Drift' post"
```

---

### Task 6: Write second blog post — "Vex vs LangSmith"

**Files:**
- Create: `apps/landing/content/blog/vex-vs-langsmith.mdx`

**Step 1: Create the post**

```mdx
---
title: "Vex vs LangSmith: Runtime Reliability vs Tracing"
description: "LangSmith traces what happened. Vex prevents bad output from reaching users. Here's when to use each — and why most teams need both."
date: "2026-02-19"
author: "Vex Team"
tags: ["comparison", "LangSmith"]
---

## Two Different Problems

LangSmith and Vex solve fundamentally different problems:

- **LangSmith** answers: *"What did my agent do?"* — It traces LLM calls, logs inputs/outputs, and helps you debug after something goes wrong.
- **Vex** answers: *"Is my agent still behaving correctly?"* — It monitors behavioral drift in real-time and auto-corrects before bad output reaches users.

They're complementary, not competing. But the distinction matters for how you architect your production stack.

## Feature Comparison

| Capability | LangSmith | Vex |
|---|---|---|
| **LLM call tracing** | ✅ Deep tracing with full chain visibility | ✅ Observes all calls |
| **Production monitoring** | ✅ Logs and dashboards | ✅ Real-time behavioral monitoring |
| **Drift detection** | ❌ No behavioral baseline comparison | ✅ Continuous drift detection |
| **Auto-correction** | ❌ Alert only | ✅ Blocks/rewrites bad output in real-time |
| **Eval integration** | ✅ Strong pre-deploy evals | ✅ Continuous production evals |
| **Framework support** | Best with LangChain | LangChain, CrewAI, OpenAI, any Python/TS |
| **Open source** | ❌ Closed source | ✅ Apache 2.0 |
| **Setup time** | ~30 minutes | ~5 minutes |
| **Pricing** | Free tier: 5K traces/month | Free tier available |

## When to Use LangSmith

LangSmith is the right choice when you need:

- **Deep debugging** — Step through every chain link, see exactly what each tool returned
- **LangChain-native development** — If your entire stack is LangChain, the integration is seamless
- **Pre-production evaluation** — Run datasets against your agent and compare results
- **Team collaboration** — Share traces with teammates for debugging sessions

## When to Use Vex

Vex is the right choice when you need:

- **Production guardrails** — Prevent hallucinations and policy violations from reaching users
- **Drift detection** — Know when your agent's behavior changes before customers complain
- **Auto-correction** — Automatically fix bad output without human intervention
- **Framework flexibility** — Use any agent framework, not just LangChain
- **Zero-latency monitoring** — Async mode adds no latency to your agent's responses

## Using Both Together

The strongest production setup uses both:

1. **LangSmith for development** — Debug your agent, run evals, iterate on prompts
2. **Vex for production** — Monitor drift, catch hallucinations, auto-correct in real-time

```python
from langchain import ...
from vex_sdk import guard

# LangSmith traces the chain (configured via env vars)
# Vex guards the output

@guard.watch()
def my_agent(input: str) -> str:
    chain = prompt | llm | parser
    return chain.invoke({"input": input})
```

LangSmith tells you what your agent did. Vex makes sure it keeps doing it correctly.

## The Bottom Line

If you're building with LangChain and need debugging tools, start with LangSmith. If you're running agents in production and need to prevent bad output from reaching users, add Vex. If you're serious about production reliability, use both.

---

*Try Vex free — [get started in 5 minutes](https://tryvex.dev).*
```

**Step 2: Build and verify**

Run: `pnpm --filter landing build`
Expected: Build succeeds.

**Step 3: Commit**

```bash
git add apps/landing/content/blog/vex-vs-langsmith.mdx
git commit -m "content(blog): add 'Vex vs LangSmith' comparison post"
```

---

### Task 7: Write third blog post — "Add Guardrails to LangChain"

**Files:**
- Create: `apps/landing/content/blog/add-guardrails-to-langchain.mdx`

**Step 1: Create the post**

```mdx
---
title: "How to Add Guardrails to Your LangChain Agent in 5 Minutes"
description: "A step-by-step guide to adding runtime guardrails to any LangChain agent using the Vex SDK. Catch hallucinations, drift, and policy violations automatically."
date: "2026-02-19"
author: "Vex Team"
tags: ["tutorial", "LangChain", "guardrails"]
---

## Why Your LangChain Agent Needs Guardrails

You've built a LangChain agent. It works great in development. Your evals pass. You ship it to production.

Then reality hits:

- A user asks something your evals didn't cover → hallucination
- The model gets updated → subtle behavioral change
- Context window fills up → degraded output quality

Evals catch problems before deployment. Guardrails catch problems during deployment. You need both.

## Prerequisites

- A working LangChain agent (Python)
- A Vex account ([sign up free](https://app.tryvex.dev))
- 5 minutes

## Step 1: Install the SDK

```bash
pip install vex-sdk
```

## Step 2: Get Your API Key

Sign up at [tryvex.dev](https://app.tryvex.dev) and copy your API key from the dashboard.

Set it as an environment variable:

```bash
export VEX_API_KEY=your_api_key_here
```

## Step 3: Wrap Your Agent

Here's a typical LangChain agent:

```python
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

llm = ChatOpenAI(model="gpt-4o")
prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a helpful support agent for Acme Corp."),
    ("human", "{input}"),
])
chain = prompt | llm

def support_agent(user_input: str) -> str:
    response = chain.invoke({"input": user_input})
    return response.content
```

Add Vex with three lines:

```python
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from vex_sdk import guard  # 1. Import

llm = ChatOpenAI(model="gpt-4o")
prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a helpful support agent for Acme Corp."),
    ("human", "{input}"),
])
chain = prompt | llm

@guard.watch()  # 2. Decorate
def support_agent(user_input: str) -> str:
    response = chain.invoke({"input": user_input})
    return response.content
```

That's it. Vex now:

- **Observes** every call to `support_agent`
- **Learns** the baseline behavior from the first requests
- **Detects** when responses drift from the baseline
- **Corrects** hallucinations and policy violations automatically

## Step 4: Deploy

Deploy your agent as usual. No infrastructure changes needed. Vex runs alongside your existing setup.

```bash
python app.py
# or
uvicorn app:app --host 0.0.0.0
```

Check the Vex dashboard to see live monitoring data from the first request.

## What Happens Next

Over the first few hours, Vex learns your agent's normal behavior patterns. After that:

- **Hallucinations** — If the agent states something that contradicts its training or retrieved context, Vex flags and optionally auto-corrects
- **Drift** — If the agent's response distribution shifts (shorter responses, different tone, skipped steps), Vex alerts you
- **Policy violations** — If you define policies (e.g., "never discuss competitors"), Vex enforces them at runtime

## Async vs Sync Mode

By default, Vex runs in **async mode** — zero added latency. Verification happens in the background.

For critical paths where you need to block bad output:

```python
@guard.watch(mode="sync")
def critical_agent(user_input: str) -> str:
    response = chain.invoke({"input": user_input})
    return response.content
```

Sync mode adds 200-500ms for the verification step, but guarantees no bad output reaches users.

## Next Steps

- [Read the full docs](https://docs.tryvex.dev)
- [Star us on GitHub](https://github.com/Vex-AI-Dev/Python-SDK)
- [Join the community](https://x.com/tryvex)

---

*Guardrails in 5 minutes. [Start free](https://tryvex.dev).*
```

**Step 2: Build and verify**

Run: `pnpm --filter landing build`
Expected: Build succeeds.

**Step 3: Commit**

```bash
git add apps/landing/content/blog/add-guardrails-to-langchain.mdx
git commit -m "content(blog): add 'Add Guardrails to LangChain' tutorial post"
```

---

### Task 8: Create comparison page template and Vex vs LangSmith

**Files:**
- Create: `apps/landing/app/compare/langsmith/page.tsx`

**Step 1: Create the page**

```tsx
import type { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Vex vs LangSmith — Runtime Reliability vs Tracing',
  description:
    'Compare Vex and LangSmith for AI agent monitoring. LangSmith traces what happened. Vex prevents bad output from reaching users.',
  keywords: [
    'LangSmith alternatives',
    'Vex vs LangSmith',
    'AI agent monitoring',
    'LangChain monitoring',
  ],
};

const features = [
  { name: 'LLM call tracing', vex: true, competitor: true },
  { name: 'Production monitoring', vex: true, competitor: true },
  { name: 'Behavioral drift detection', vex: true, competitor: false },
  { name: 'Auto-correction', vex: true, competitor: false },
  { name: 'Hallucination blocking', vex: true, competitor: false },
  { name: 'Pre-deploy evals', vex: true, competitor: true },
  { name: 'Framework agnostic', vex: true, competitor: false },
  { name: 'Open source', vex: true, competitor: false },
  { name: 'Zero-latency async mode', vex: true, competitor: false },
  { name: 'Self-hosted option', vex: true, competitor: true },
];

export default function CompareLangSmith() {
  return (
    <div className="container py-24">
      <div className="mx-auto max-w-[800px]">
        <div className="mb-4 text-[13px] font-medium uppercase tracking-widest text-emerald-500">
          Comparison
        </div>
        <h1 className="mb-4 text-3xl font-bold text-white sm:text-4xl">
          Vex vs LangSmith
        </h1>
        <p className="mb-12 max-w-[600px] text-lg text-[#a2a2a2]">
          LangSmith traces what happened. Vex prevents bad output from reaching
          users. Here&apos;s how they compare.
        </p>

        {/* Feature table */}
        <div className="mb-16 overflow-hidden rounded-xl border border-[#252525]">
          <div className="grid grid-cols-[1fr_80px_80px] bg-[#161616] px-6 py-3 text-sm font-medium">
            <span className="text-[#585858]">Feature</span>
            <span className="text-center text-emerald-500">Vex</span>
            <span className="text-center text-[#585858]">LangSmith</span>
          </div>
          {features.map((f) => (
            <div
              key={f.name}
              className="grid grid-cols-[1fr_80px_80px] border-t border-[#252525] px-6 py-3 text-sm"
            >
              <span className="text-[#a2a2a2]">{f.name}</span>
              <span className="text-center">
                {f.vex ? (
                  <span className="text-emerald-500">✓</span>
                ) : (
                  <span className="text-[#585858]">—</span>
                )}
              </span>
              <span className="text-center">
                {f.competitor ? (
                  <span className="text-white">✓</span>
                ) : (
                  <span className="text-[#585858]">—</span>
                )}
              </span>
            </div>
          ))}
        </div>

        {/* Key differences */}
        <h2 className="mb-6 text-2xl font-semibold text-white">
          Key Differences
        </h2>
        <div className="mb-16 grid gap-4 md:grid-cols-2">
          <div className="rounded-xl border border-[#252525] bg-[#0a0a0a] p-6">
            <h3 className="mb-2 font-mono text-sm font-medium text-emerald-500">
              Vex
            </h3>
            <p className="text-sm leading-relaxed text-[#a2a2a2]">
              Runtime reliability layer. Monitors agent behavior continuously,
              detects drift from learned baselines, and auto-corrects
              hallucinations before they reach users. Works with any framework.
              Open source (Apache 2.0).
            </p>
          </div>
          <div className="rounded-xl border border-[#252525] bg-[#0a0a0a] p-6">
            <h3 className="mb-2 font-mono text-sm font-medium text-[#a2a2a2]">
              LangSmith
            </h3>
            <p className="text-sm leading-relaxed text-[#a2a2a2]">
              Tracing and evaluation platform. Deep visibility into LangChain
              execution chains. Best for debugging during development and running
              pre-deploy evaluations. Closed source, best with LangChain.
            </p>
          </div>
        </div>

        {/* Verdict */}
        <h2 className="mb-4 text-2xl font-semibold text-white">The Verdict</h2>
        <p className="mb-8 text-[15px] leading-relaxed text-[#a2a2a2]">
          Use LangSmith for development debugging and pre-deploy evals. Use Vex
          for production monitoring and real-time guardrails. For the strongest
          setup, use both — LangSmith tells you what your agent did, Vex makes
          sure it keeps doing it correctly.
        </p>

        {/* CTA */}
        <div className="flex items-center gap-3">
          <Link
            href="https://app.tryvex.dev"
            className="inline-flex h-12 items-center rounded-lg bg-emerald-500 px-7 text-[15px] font-semibold text-white transition-colors hover:bg-emerald-400"
          >
            Try Vex Free
          </Link>
          <Link
            href="/blog/vex-vs-langsmith"
            className="inline-flex h-12 items-center rounded-lg border border-[#252525] px-7 text-[15px] font-medium text-[#a2a2a2] transition-colors hover:border-[#585858] hover:text-white"
          >
            Read Full Comparison&ensp;&rarr;
          </Link>
        </div>
      </div>
    </div>
  );
}
```

**Step 2: Build and verify**

Run: `pnpm --filter landing build`
Expected: Build succeeds. `/compare/langsmith` route appears.

**Step 3: Commit**

```bash
git add apps/landing/app/compare/langsmith/page.tsx
git commit -m "feat(landing): add Vex vs LangSmith comparison page"
```

---

### Task 9: Create Vex vs Langfuse comparison page

**Files:**
- Create: `apps/landing/app/compare/langfuse/page.tsx`

**Step 1: Create the page**

Same template structure as Task 8, with Langfuse-specific content:

- Title: "Vex vs Langfuse — Observability vs Runtime Reliability"
- Description: "Both open source. Langfuse traces and evaluates. Vex detects drift and auto-corrects. Compare features side by side."
- Keywords: "Langfuse alternatives", "Vex vs Langfuse", "Langfuse vs LangSmith"
- Feature differences: Langfuse has tracing, evals, prompt management, dataset management. Vex adds drift detection, auto-correction, hallucination blocking.
- Angle: Langfuse = observability. Vex = observability + guardrails. Use Langfuse for development visibility. Use Vex for production safety. Use both for complete coverage.

Follow the exact same component structure as the LangSmith page — same grid layout, same feature table format, same CTA section. Change the data and copy.

**Step 2: Build and verify**

Run: `pnpm --filter landing build`
Expected: Build succeeds.

**Step 3: Commit**

```bash
git add apps/landing/app/compare/langfuse/page.tsx
git commit -m "feat(landing): add Vex vs Langfuse comparison page"
```

---

### Task 10: Create Vex vs Guardrails AI comparison page

**Files:**
- Create: `apps/landing/app/compare/guardrails-ai/page.tsx`

**Step 1: Create the page**

Same template structure as Task 8, with Guardrails AI-specific content:

- Title: "Vex vs Guardrails AI — Runtime Reliability vs Schema Validation"
- Description: "Guardrails AI validates input/output schemas. Vex detects behavioral drift over time. Compare approaches to AI safety."
- Keywords: "Guardrails AI alternatives", "AI guardrails", "Vex vs Guardrails AI"
- Feature differences: Guardrails AI has schema validation, structural output enforcement, validators. Vex adds behavioral drift detection, continuous learning, auto-correction beyond schema.
- Angle: Guardrails AI checks structure. Vex checks behavior. A response can be structurally valid but semantically drifted. You need both layers.

Follow the exact same component structure. Change the data and copy.

**Step 2: Build and verify**

Run: `pnpm --filter landing build`
Expected: Build succeeds.

**Step 3: Commit**

```bash
git add apps/landing/app/compare/guardrails-ai/page.tsx
git commit -m "feat(landing): add Vex vs Guardrails AI comparison page"
```

---

### Task 11: Create Agent Health Score tool

**Files:**
- Create: `apps/landing/app/tools/agent-health-score/page.tsx`

**Step 1: Create the interactive tool page**

This is a `'use client'` component with a multi-step questionnaire. Questions:

1. **Framework** — What framework does your agent use? (LangChain / CrewAI / OpenAI / Custom / Other)
2. **Monitoring** — Do you have production monitoring? (None / Basic logging / LLM tracing / Full observability)
3. **Evals** — Do you run evaluations? (None / Manual spot-checks / Automated pre-deploy / Continuous production)
4. **Error handling** — How do you handle agent failures? (No handling / Retry / Fallback response / Auto-correction)
5. **Drift detection** — Do you monitor for behavioral drift? (No / Manual review / Automated alerts / Real-time detection + correction)
6. **Hallucination prevention** — How do you prevent hallucinations? (Nothing / Prompt engineering only / Output validation / Runtime guardrails)
7. **Deployment** — How do you deploy agent updates? (Direct push / Staging environment / Canary + rollback / Blue-green with drift comparison)
8. **Incident response** — How do you handle production issues? (Wait for reports / Periodic checks / Automated alerts / Auto-remediation)

Scoring: Each answer = 0-3 points per category. Total out of 100. Categories: Monitoring (25), Safety (25), Testing (25), Operations (25).

Results show:
- Overall score with color (red <40, amber 40-70, green >70)
- Category breakdown bars
- Recommendations per category (with natural Vex CTAs for low-scoring areas)
- Shareable URL via query param encoding

Use metadata:
- Title: "AI Agent Health Score — Free Assessment Tool"
- Description: "Score your AI agent's production readiness in 2 minutes. Get personalized recommendations for monitoring, safety, testing, and operations."
- Keywords: "AI agent production readiness", "AI agent monitoring checklist", "AI agent health check"

JSON-LD `WebApplication` schema.

**Step 2: Build and verify**

Run: `pnpm --filter landing build`
Expected: Build succeeds. `/tools/agent-health-score` route appears.

**Step 3: Commit**

```bash
git add apps/landing/app/tools/agent-health-score/page.tsx
git commit -m "feat(landing): add Agent Health Score interactive tool"
```

---

### Task 12: Update navigation, sitemap, and footer

**Files:**
- Modify: `apps/landing/app/_components/site-header.tsx:12-41`
- Modify: `apps/landing/app/_components/site-footer.tsx:3-27`
- Modify: `apps/landing/app/sitemap.ts`

**Step 1: Add Blog link to header nav**

In `site-header.tsx`, add a Blog link in the nav between "Quick Start" and "Docs":

```tsx
<Link
  href="/blog"
  className="text-sm text-[#a2a2a2] transition-colors hover:text-white"
>
  Blog
</Link>
```

**Step 2: Add links to footer**

In `site-footer.tsx`, add to the Product section:
- `{ href: '/blog', label: 'Blog' }`
- `{ href: '/compare/langsmith', label: 'Vex vs LangSmith' }`

Add a new "Tools" section or add to Product:
- `{ href: '/tools/agent-health-score', label: 'Agent Health Score' }`

**Step 3: Update sitemap**

In `sitemap.ts`, add entries for:
- `/blog` (weekly, priority 0.8)
- `/compare/langsmith` (monthly, priority 0.7)
- `/compare/langfuse` (monthly, priority 0.7)
- `/compare/guardrails-ai` (monthly, priority 0.7)
- `/tools/agent-health-score` (monthly, priority 0.6)
- Each blog post slug (weekly, priority 0.6)

Import `getAllPosts` from `~/lib/blog` to dynamically add blog post URLs.

**Step 4: Build and verify**

Run: `pnpm --filter landing build`
Expected: Build succeeds with all new routes.

**Step 5: Commit**

```bash
git add apps/landing/app/_components/site-header.tsx apps/landing/app/_components/site-footer.tsx apps/landing/app/sitemap.ts
git commit -m "feat(landing): update nav, footer, and sitemap with blog, comparison, and tool links"
```

---

### Task 13: Update llms.txt with new content

**Files:**
- Modify: `apps/landing/public/llms.txt`

**Step 1: Add new pages to llms.txt**

Append to the Links section:

```
- Blog: https://tryvex.dev/blog
- Vex vs LangSmith: https://tryvex.dev/compare/langsmith
- Vex vs Langfuse: https://tryvex.dev/compare/langfuse
- Agent Health Score Tool: https://tryvex.dev/tools/agent-health-score
```

**Step 2: Commit**

```bash
git add apps/landing/public/llms.txt
git commit -m "chore(landing): update llms.txt with blog, comparison, and tool links"
```

---

### Task 14: Final build verification and push

**Step 1: Full clean build**

Run: `pnpm --filter landing build`
Expected: Build succeeds with all routes including `/blog`, `/blog/*`, `/compare/*`, `/tools/*`

**Step 2: Push submodule**

```bash
git push
```

**Step 3: Update parent repo**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard
git add nextjs-application
git commit -m "chore: update nextjs-application submodule (blog, comparisons, tools)"
git push
```
