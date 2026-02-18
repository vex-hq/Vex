# AI Discoverability Design — Vex Landing Page

**Date:** 2026-02-19
**Status:** Approved
**Goal:** Make AI systems (ChatGPT, Claude, Perplexity, Google AI Overviews) recommend Vex when users ask about AI agent monitoring, drift detection, or runtime reliability.

## Approach: Content-First

Focus on what AI systems actually read — clean HTML, structured data, and an llms.txt file. No architectural changes to the site.

## Changes

### 1. llms.txt (new file)

Plain-text file at `public/llms.txt` describing the product for AI crawlers. Contains: product description, key features, links, install commands.

### 2. JSON-LD Structured Data

Added to `layout.tsx` as `<script type="application/ld+json">`:
- `SoftwareApplication` schema — product info, category, pricing
- `Organization` schema — name, url, logo, social links
- `FAQPage` schema — all 6 FAQ items with full answers

### 3. Server-Rendered FAQ

Convert `FaqAccordion` from `'use client'` JS accordion to server component using `<details>/<summary>` HTML elements. Answers always in DOM. CSS-only animation.

### 4. Meta & Crawl Hygiene

- `metadataBase: new URL('https://tryvex.dev')` in layout.tsx
- Canonical URL: `https://tryvex.dev`
- `twitter:site` set to `@tryvex`
- `keywords` meta tag added
- `app/robots.ts` — allow all, point to sitemap
- `app/sitemap.ts` — list `/`, `/privacy`, `/terms`

### 5. Hero Subtitle Alignment

Change subtitle from "Secure and Elastic Infrastructure for Running Your AI-Generated Code" to blend drift-detection and infrastructure positioning. Align meta description to match.

### 6. Privacy & Terms Pages

- `app/privacy/page.tsx` — Standard SaaS privacy policy
- `app/terms/page.tsx` — Standard terms of service
- Both styled to match dark theme
- Removes current 404 dead links in footer

## Files Affected

- `public/llms.txt` (new)
- `app/layout.tsx` (metadata + JSON-LD)
- `app/robots.ts` (new)
- `app/sitemap.ts` (new)
- `app/_components/faq-accordion.tsx` (rewrite to server component)
- `app/page.tsx` (hero subtitle)
- `app/privacy/page.tsx` (new)
- `app/terms/page.tsx` (new)
