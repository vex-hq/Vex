# AI Discoverability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make AI systems (ChatGPT, Claude, Perplexity, Google AI Overviews) recommend Vex by adding structured data, crawl hygiene, server-rendered FAQ, and missing pages.

**Architecture:** All changes are in `apps/landing/`. Add static files to `public/`, Next.js App Router route handlers for robots/sitemap, JSON-LD in layout, and new page routes for privacy/terms. Convert FAQ from client to server component.

**Tech Stack:** Next.js App Router, TypeScript, Tailwind CSS 4

---

### Task 1: Add llms.txt

**Files:**
- Create: `apps/landing/public/llms.txt`

**Step 1: Create the file**

```txt
# Vex

> Runtime reliability for AI agents in production.

Vex is an open-source runtime reliability layer that detects when AI agent behavior
silently drifts in production. It observes every LLM call, corrects hallucinations
and policy violations in real time, and continuously optimizes agent performance.

## Key Features
- Real-time observability for every agent action
- Automatic correction of hallucinations, drift, and policy violations
- Continuous optimization of prompts, thresholds, and correction strategies
- Works with LangChain, CrewAI, OpenAI Assistants, and any Python/TypeScript agent

## Links
- Website: https://tryvex.dev
- Docs: https://docs.tryvex.dev
- GitHub: https://github.com/Vex-AI-Dev/Python-SDK
- API: https://api.tryvex.dev

## Install
pip install vex-sdk
npm install @vex_dev/sdk
```

**Step 2: Verify it serves**

Run: `pnpm --filter landing build`
Expected: Build succeeds. File will be served at `/llms.txt`.

**Step 3: Commit**

```bash
git add apps/landing/public/llms.txt
git commit -m "feat(landing): add llms.txt for AI discoverability"
```

---

### Task 2: Add robots.ts and sitemap.ts

**Files:**
- Create: `apps/landing/app/robots.ts`
- Create: `apps/landing/app/sitemap.ts`

**Step 1: Create robots.ts**

```typescript
import type { MetadataRoute } from 'next';

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: '*',
        allow: '/',
      },
    ],
    sitemap: 'https://tryvex.dev/sitemap.xml',
  };
}
```

**Step 2: Create sitemap.ts**

```typescript
import type { MetadataRoute } from 'next';

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    {
      url: 'https://tryvex.dev',
      lastModified: new Date(),
      changeFrequency: 'weekly',
      priority: 1,
    },
    {
      url: 'https://tryvex.dev/privacy',
      lastModified: new Date(),
      changeFrequency: 'monthly',
      priority: 0.3,
    },
    {
      url: 'https://tryvex.dev/terms',
      lastModified: new Date(),
      changeFrequency: 'monthly',
      priority: 0.3,
    },
  ];
}
```

**Step 3: Build and verify**

Run: `pnpm --filter landing build`
Expected: Build succeeds. Routes `/robots.txt` and `/sitemap.xml` appear in output.

**Step 4: Commit**

```bash
git add apps/landing/app/robots.ts apps/landing/app/sitemap.ts
git commit -m "feat(landing): add robots.txt and sitemap.xml route handlers"
```

---

### Task 3: Fix metadata in layout.tsx

**Files:**
- Modify: `apps/landing/app/layout.tsx:15-37`

**Step 1: Update the metadata export**

Replace the existing `metadata` export (lines 15-37) with:

```typescript
export const metadata: Metadata = {
  metadataBase: new URL('https://tryvex.dev'),
  title: 'Vex — Runtime reliability for AI agents',
  description:
    "Vex is the open-source runtime reliability layer that detects when your AI agent's behavior silently changes in production. Before your customers notice.",
  keywords: [
    'AI agent monitoring',
    'runtime reliability',
    'LLM observability',
    'agent drift detection',
    'hallucination detection',
    'AI guardrails',
    'LangChain monitoring',
    'CrewAI monitoring',
    'OpenAI agent monitoring',
    'production AI agents',
  ],
  alternates: {
    canonical: 'https://tryvex.dev',
  },
  icons: {
    icon: '/favicon.ico',
  },
  openGraph: {
    title: 'Vex — Runtime reliability for AI agents',
    description:
      "Detect when your AI agent's behavior silently changes in production. Before your customers notice.",
    url: 'https://tryvex.dev',
    images: [{ url: '/images/og-image.png', width: 800, height: 800 }],
    siteName: 'Vex',
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    site: '@tryvex',
    title: 'Vex — Runtime reliability for AI agents',
    description:
      "Detect when your AI agent's behavior silently changes in production.",
    images: ['/images/og-image.png'],
  },
};
```

**Step 2: Build and verify**

Run: `pnpm --filter landing build`
Expected: Build succeeds.

**Step 3: Commit**

```bash
git add apps/landing/app/layout.tsx
git commit -m "feat(landing): add metadataBase, canonical URL, keywords, twitter:site"
```

---

### Task 4: Add JSON-LD structured data

**Files:**
- Modify: `apps/landing/app/layout.tsx:51` (inside `<body>`, before the children div)

**Step 1: Add JSON-LD script tag**

Insert the following right after the `<body>` opening tag (line 51), before the chevron pattern div:

```tsx
<script
  type="application/ld+json"
  dangerouslySetInnerHTML={{
    __html: JSON.stringify([
      {
        '@context': 'https://schema.org',
        '@type': 'SoftwareApplication',
        name: 'Vex',
        description:
          "Open-source runtime reliability layer that detects when AI agent behavior silently drifts in production. Observes every LLM call, corrects hallucinations and policy violations in real time.",
        url: 'https://tryvex.dev',
        applicationCategory: 'DeveloperApplication',
        operatingSystem: 'Any',
        offers: {
          '@type': 'Offer',
          price: '0',
          priceCurrency: 'USD',
          description: 'Free tier available',
        },
        softwareHelp: {
          '@type': 'WebPage',
          url: 'https://docs.tryvex.dev',
        },
        downloadUrl: 'https://pypi.org/project/vex-sdk/',
        codeRepository: 'https://github.com/Vex-AI-Dev/Python-SDK',
        license: 'https://opensource.org/licenses/Apache-2.0',
      },
      {
        '@context': 'https://schema.org',
        '@type': 'Organization',
        name: 'Vex',
        url: 'https://tryvex.dev',
        logo: 'https://tryvex.dev/images/og-image.png',
        sameAs: [
          'https://github.com/Vex-AI-Dev',
          'https://x.com/tryvex',
        ],
      },
      {
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        mainEntity: [
          {
            '@type': 'Question',
            name: 'What is Vex?',
            acceptedAnswer: {
              '@type': 'Answer',
              text: "Vex is an open-source runtime reliability layer for AI agents. It detects when your agent's behavior silently changes in production — hallucinations, drift, schema violations — and auto-corrects before your users notice.",
            },
          },
          {
            '@type': 'Question',
            name: 'How is Vex different from evals or tracing?',
            acceptedAnswer: {
              '@type': 'Answer',
              text: "Evals test your agent before deployment. Tracing shows you what happened after something breaks. Vex runs continuously in production, catching behavioral drift in real-time and auto-correcting on the fly. They're complementary — Vex fills the gap between pre-deploy testing and post-mortem analysis.",
            },
          },
          {
            '@type': 'Question',
            name: 'How long does it take to set up?',
            acceptedAnswer: {
              '@type': 'Answer',
              text: 'About 5 minutes. Install the SDK (pip install vex-sdk or npm install @vex_dev/sdk), add 3 lines of code to wrap your agent function, and deploy. Vex starts learning from the first request.',
            },
          },
          {
            '@type': 'Question',
            name: 'What frameworks does Vex support?',
            acceptedAnswer: {
              '@type': 'Answer',
              text: 'Vex works with LangChain, CrewAI, OpenAI Assistants, and any custom Python or TypeScript agent. If your code calls an LLM, Vex can watch it.',
            },
          },
          {
            '@type': 'Question',
            name: 'Is Vex open source?',
            acceptedAnswer: {
              '@type': 'Answer',
              text: 'Yes. Vex is fully open source under the Apache 2.0 license. Both the Python SDK and TypeScript SDK are available on GitHub.',
            },
          },
          {
            '@type': 'Question',
            name: 'Does Vex add latency?',
            acceptedAnswer: {
              '@type': 'Answer',
              text: 'In async mode (default), Vex adds zero latency — verification happens in the background. In sync mode, Vex adds a verification step before returning the output, which typically takes 200-500ms depending on the checks enabled.',
            },
          },
        ],
      },
    ]),
  }}
/>
```

**Step 2: Build and verify**

Run: `pnpm --filter landing build`
Expected: Build succeeds.

**Step 3: Commit**

```bash
git add apps/landing/app/layout.tsx
git commit -m "feat(landing): add JSON-LD structured data (SoftwareApplication, Organization, FAQPage)"
```

---

### Task 5: Convert FAQ to server-rendered component

**Files:**
- Modify: `apps/landing/app/_components/faq-accordion.tsx` (full rewrite)

**Step 1: Rewrite as server component with `<details>/<summary>`**

Replace entire file with:

```tsx
const faqs = [
  {
    q: 'What is Vex?',
    a: "Vex is an open-source runtime reliability layer for AI agents. It detects when your agent's behavior silently changes in production — hallucinations, drift, schema violations — and auto-corrects before your users notice.",
  },
  {
    q: 'How is Vex different from evals or tracing?',
    a: "Evals test your agent before deployment. Tracing shows you what happened after something breaks. Vex runs continuously in production, catching behavioral drift in real-time and auto-correcting on the fly. They're complementary — Vex fills the gap between pre-deploy testing and post-mortem analysis.",
  },
  {
    q: 'How long does it take to set up?',
    a: 'About 5 minutes. Install the SDK (pip install vex-sdk or npm install @vex_dev/sdk), add 3 lines of code to wrap your agent function, and deploy. Vex starts learning from the first request.',
  },
  {
    q: 'What frameworks does Vex support?',
    a: 'Vex works with LangChain, CrewAI, OpenAI Assistants, and any custom Python or TypeScript agent. If your code calls an LLM, Vex can watch it.',
  },
  {
    q: 'Is Vex open source?',
    a: 'Yes. Vex is fully open source under the Apache 2.0 license. Both the Python SDK and TypeScript SDK are available on GitHub.',
  },
  {
    q: 'Does Vex add latency?',
    a: 'In async mode (default), Vex adds zero latency — verification happens in the background. In sync mode, Vex adds a verification step before returning the output, which typically takes 200-500ms depending on the checks enabled.',
  },
];

export function FaqAccordion() {
  return (
    <section id="faq" className="border-t border-[#252525] py-20">
      <div className="container">
        <div className="mb-4 text-[13px] font-medium uppercase tracking-widest text-emerald-500">
          FAQ
        </div>
        <h2 className="mb-12 max-w-[600px] text-3xl font-semibold leading-tight tracking-tight text-white sm:text-4xl">
          Frequently asked questions
        </h2>

        <div className="mx-auto max-w-[800px]">
          {faqs.map((faq, i) => (
            <details
              key={i}
              className="group border-b border-[#252525]"
            >
              <summary className="flex cursor-pointer items-center justify-between py-5 text-left [&::-webkit-details-marker]:hidden list-none">
                <span className="pr-4 text-[15px] font-medium text-white">
                  {faq.q}
                </span>
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 20 20"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  className="shrink-0 text-[#585858] transition-transform duration-200 group-open:rotate-45"
                >
                  <line x1="10" y1="4" x2="10" y2="16" />
                  <line x1="4" y1="10" x2="16" y2="10" />
                </svg>
              </summary>
              <p className="pb-5 text-sm leading-relaxed text-[#a2a2a2]">
                {faq.a}
              </p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}
```

**Step 2: Build and verify**

Run: `pnpm --filter landing build`
Expected: Build succeeds. FAQ answers are now in the static HTML output.

**Step 3: Commit**

```bash
git add apps/landing/app/_components/faq-accordion.tsx
git commit -m "refactor(landing): convert FAQ to server component with details/summary"
```

---

### Task 6: Update hero subtitle

**Files:**
- Modify: `apps/landing/app/page.tsx:28-32`

**Step 1: Replace the subtitle**

Change lines 28-32 from:

```tsx
<p className="mb-10 max-w-[460px] text-[17px] leading-relaxed text-[#a2a2a2]">
  Secure and Elastic Infrastructure for
  <br />
  Running Your AI-Generated Code.
</p>
```

To:

```tsx
<p className="mb-10 max-w-[460px] text-[17px] leading-relaxed text-[#a2a2a2]">
  Detect drift. Correct hallucinations.
  <br />
  Reliable AI agents in production.
</p>
```

**Step 2: Build and verify**

Run: `pnpm --filter landing build`
Expected: Build succeeds.

**Step 3: Commit**

```bash
git add apps/landing/app/page.tsx
git commit -m "fix(landing): align hero subtitle with product positioning"
```

---

### Task 7: Create privacy policy page

**Files:**
- Create: `apps/landing/app/privacy/page.tsx`

**Step 1: Create the page**

```tsx
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Privacy Policy — Vex',
  description: 'Privacy policy for Vex, the runtime reliability layer for AI agents.',
};

export default function PrivacyPage() {
  return (
    <div className="container py-24">
      <h1 className="mb-8 text-3xl font-bold text-white">Privacy Policy</h1>
      <div className="prose prose-invert max-w-[720px] text-[#a2a2a2] prose-headings:text-white prose-headings:font-semibold prose-h2:text-xl prose-h2:mt-10 prose-h2:mb-4 prose-p:leading-relaxed prose-p:text-[#a2a2a2] prose-li:text-[#a2a2a2] prose-strong:text-white">
        <p className="text-sm text-[#585858]">Last updated: February 19, 2026</p>

        <h2>1. Introduction</h2>
        <p>
          Vex (&quot;we&quot;, &quot;our&quot;, or &quot;us&quot;) operates the tryvex.dev website and the Vex SDK and API services (collectively, the &quot;Service&quot;). This Privacy Policy explains how we collect, use, disclose, and safeguard your information when you use our Service.
        </p>

        <h2>2. Information We Collect</h2>
        <p><strong>Account Information:</strong> When you create an account, we collect your name, email address, and authentication credentials.</p>
        <p><strong>Usage Data:</strong> We collect information about how you interact with our Service, including API call metadata, SDK configuration, and feature usage patterns.</p>
        <p><strong>Agent Telemetry:</strong> When you use the Vex SDK, we collect metadata about agent execution (e.g., latency, correction counts, drift scores). We do not collect the content of your agent&apos;s inputs or outputs unless you explicitly enable content logging.</p>
        <p><strong>Technical Data:</strong> We collect IP addresses, browser type, operating system, and device information for security and analytics purposes.</p>

        <h2>3. How We Use Your Information</h2>
        <p>We use your information to:</p>
        <ul>
          <li>Provide, maintain, and improve the Service</li>
          <li>Monitor and analyze usage patterns and trends</li>
          <li>Detect, prevent, and address technical issues</li>
          <li>Send you service-related communications</li>
          <li>Comply with legal obligations</li>
        </ul>

        <h2>4. Data Retention</h2>
        <p>
          We retain your account information for as long as your account is active. Agent telemetry data is retained for 90 days by default. You can request deletion of your data at any time by contacting us at info@tryvex.dev.
        </p>

        <h2>5. Data Sharing</h2>
        <p>
          We do not sell your personal information. We may share data with service providers who assist in operating our Service (e.g., hosting, analytics), subject to confidentiality agreements. We may disclose information if required by law.
        </p>

        <h2>6. Security</h2>
        <p>
          We implement industry-standard security measures including encryption in transit (TLS 1.3) and at rest (AES-256). API keys are hashed and never stored in plaintext.
        </p>

        <h2>7. Your Rights</h2>
        <p>You have the right to:</p>
        <ul>
          <li>Access your personal data</li>
          <li>Correct inaccurate data</li>
          <li>Request deletion of your data</li>
          <li>Export your data in a portable format</li>
          <li>Withdraw consent at any time</li>
        </ul>

        <h2>8. Cookies</h2>
        <p>
          We use essential cookies for authentication and session management. We use analytics cookies only with your consent. You can manage cookie preferences in your browser settings.
        </p>

        <h2>9. Changes to This Policy</h2>
        <p>
          We may update this Privacy Policy from time to time. We will notify you of material changes by posting the new policy on this page and updating the &quot;Last updated&quot; date.
        </p>

        <h2>10. Contact Us</h2>
        <p>
          If you have questions about this Privacy Policy, contact us at{' '}
          <a href="mailto:info@tryvex.dev" className="text-emerald-500 hover:text-emerald-400">
            info@tryvex.dev
          </a>.
        </p>
      </div>
    </div>
  );
}
```

**Step 2: Build and verify**

Run: `pnpm --filter landing build`
Expected: Build succeeds. `/privacy` route appears in output.

**Step 3: Commit**

```bash
git add apps/landing/app/privacy/page.tsx
git commit -m "feat(landing): add privacy policy page"
```

---

### Task 8: Create terms of service page

**Files:**
- Create: `apps/landing/app/terms/page.tsx`

**Step 1: Create the page**

```tsx
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Terms of Service — Vex',
  description: 'Terms of service for Vex, the runtime reliability layer for AI agents.',
};

export default function TermsPage() {
  return (
    <div className="container py-24">
      <h1 className="mb-8 text-3xl font-bold text-white">Terms of Service</h1>
      <div className="prose prose-invert max-w-[720px] text-[#a2a2a2] prose-headings:text-white prose-headings:font-semibold prose-h2:text-xl prose-h2:mt-10 prose-h2:mb-4 prose-p:leading-relaxed prose-p:text-[#a2a2a2] prose-li:text-[#a2a2a2] prose-strong:text-white">
        <p className="text-sm text-[#585858]">Last updated: February 19, 2026</p>

        <h2>1. Acceptance of Terms</h2>
        <p>
          By accessing or using the Vex website (tryvex.dev), SDK, API, or any related services (collectively, the &quot;Service&quot;), you agree to be bound by these Terms of Service. If you do not agree, do not use the Service.
        </p>

        <h2>2. Description of Service</h2>
        <p>
          Vex provides a runtime reliability layer for AI agents, including SDKs, APIs, and a dashboard for monitoring, correcting, and optimizing AI agent behavior in production environments.
        </p>

        <h2>3. Account Registration</h2>
        <p>
          You must provide accurate and complete information when creating an account. You are responsible for maintaining the security of your account credentials and API keys. You are responsible for all activities that occur under your account.
        </p>

        <h2>4. Acceptable Use</h2>
        <p>You agree not to:</p>
        <ul>
          <li>Use the Service for any unlawful purpose</li>
          <li>Attempt to gain unauthorized access to the Service or its systems</li>
          <li>Interfere with or disrupt the integrity or performance of the Service</li>
          <li>Reverse engineer, decompile, or disassemble any part of the Service (except the open-source SDK components)</li>
          <li>Use the Service to build a competing product</li>
          <li>Exceed rate limits or abuse API access</li>
        </ul>

        <h2>5. Open Source Components</h2>
        <p>
          The Vex SDK is released under the Apache 2.0 license. Your use of the open-source SDK is governed by the Apache 2.0 license terms. These Terms of Service govern your use of the hosted Service (API, dashboard, and cloud features).
        </p>

        <h2>6. Intellectual Property</h2>
        <p>
          The Service and its original content (excluding open-source components) are the property of Vex and are protected by applicable intellectual property laws. Your data remains your property.
        </p>

        <h2>7. Service Availability</h2>
        <p>
          We strive to maintain high availability but do not guarantee uninterrupted access. We may modify, suspend, or discontinue any part of the Service with reasonable notice. Scheduled maintenance windows will be communicated in advance.
        </p>

        <h2>8. Limitation of Liability</h2>
        <p>
          To the maximum extent permitted by law, Vex shall not be liable for any indirect, incidental, special, consequential, or punitive damages, including loss of profits, data, or business opportunities, arising from your use of the Service.
        </p>

        <h2>9. Indemnification</h2>
        <p>
          You agree to indemnify and hold Vex harmless from any claims, damages, or expenses arising from your use of the Service or violation of these Terms.
        </p>

        <h2>10. Termination</h2>
        <p>
          We may terminate or suspend your access immediately, without prior notice, for conduct that we believe violates these Terms or is harmful to other users or the Service. Upon termination, your right to use the Service ceases immediately.
        </p>

        <h2>11. Changes to Terms</h2>
        <p>
          We reserve the right to modify these Terms at any time. Material changes will be communicated via email or a notice on the Service. Continued use after changes constitutes acceptance.
        </p>

        <h2>12. Governing Law</h2>
        <p>
          These Terms shall be governed by and construed in accordance with applicable laws, without regard to conflict of law provisions.
        </p>

        <h2>13. Contact</h2>
        <p>
          For questions about these Terms, contact us at{' '}
          <a href="mailto:info@tryvex.dev" className="text-emerald-500 hover:text-emerald-400">
            info@tryvex.dev
          </a>.
        </p>
      </div>
    </div>
  );
}
```

**Step 2: Build and verify**

Run: `pnpm --filter landing build`
Expected: Build succeeds. `/terms` route appears in output.

**Step 3: Commit**

```bash
git add apps/landing/app/terms/page.tsx
git commit -m "feat(landing): add terms of service page"
```

---

### Task 9: Final build verification and push

**Step 1: Full clean build**

Run: `pnpm --filter landing build`
Expected: Build succeeds with routes: `/`, `/privacy`, `/terms`, `/robots.txt`, `/sitemap.xml`, `/_not-found`

**Step 2: Push submodule**

```bash
git push
```

**Step 3: Update parent repo**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard
git add nextjs-application
git commit -m "chore: update nextjs-application submodule (AI discoverability)"
git push
```
