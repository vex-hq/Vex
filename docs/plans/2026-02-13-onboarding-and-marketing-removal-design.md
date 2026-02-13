# Onboarding Flow + Marketing Pages Removal Design

**Date:** 2026-02-13
**Status:** Approved

## Overview

Two related changes:
1. Remove all marketing/landing pages — unauthenticated users redirect to `/auth/sign-in`
2. Add a Linear-style full-screen onboarding wizard for new organizations

## Part 1: Marketing Pages Removal

### What Changes
- Delete entire `app/(marketing)/` directory (45 files: homepage, blog, changelog, docs, pricing, FAQ, contact, legal pages, layouts, components)
- Modify `app/page.tsx` to check auth state:
  - Authenticated → redirect to `/home`
  - Unauthenticated → redirect to `/auth/sign-in`
- Auth pages at `/auth/*` stay untouched

### Root Page
```tsx
// app/page.tsx
import { redirect } from 'next/navigation';
import { getSupabaseServerClient } from '@kit/supabase/server-client';
import { requireUser } from '@kit/supabase/require-user';

export default async function RootPage() {
  const client = getSupabaseServerClient();
  const user = await requireUser(client, { verifyMfa: false });
  if (user.data) {
    redirect('/home');
  }
  redirect('/auth/sign-in');
}
```

## Part 2: Database Schema

### Migration 007
```sql
ALTER TABLE organizations
  ADD COLUMN onboarding_completed BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN onboarding_step INTEGER NOT NULL DEFAULT 0;

-- Mark all existing organizations as completed so they aren't blocked
UPDATE organizations SET onboarding_completed = TRUE;
```

- `onboarding_completed`: gates dashboard access
- `onboarding_step`: persists which step user was on (0-4) for resume
- Existing orgs set to `completed = true`

### Loader
`lib/agentguard/onboarding.loader.ts`:
- `loadOnboardingState(orgId)` → `{ completed, currentStep }`

## Part 3: Onboarding Wizard

### Architecture: Approach A — Dedicated /onboarding Route
Full-screen wizard at `/onboarding?account=[slug]`, no sidebar/header.

### Redirect Logic
1. Post sign-up: `/auth/callback` → `/home` → `/home/[account]`
2. Team account layout checks `onboarding_completed`
3. If `false` → server-side redirect to `/onboarding?account=[slug]`
4. `/onboarding` page checks auth + org ownership
5. If `onboarding_completed = true` → redirect to `/home/[account]`
6. Dashboard is fully blocked until onboarding completes

### 5 Wizard Steps

| Step | Title | Content | Data Persisted |
|------|-------|---------|----------------|
| 0 | Name Your Workspace | Text input for org name, optional avatar | Updates `organizations.name` |
| 1 | Invite Your Team | Email input(s) + role selector, "Skip" button | Sends team invites via MakerKit |
| 2 | Create API Key | Auto-generates key on mount, copy button, "shown once" warning | Creates key via existing `createKey` |
| 3 | Install the SDK | `pip install agentx-sdk` + init code with user's API key pre-filled | Updates `onboarding_step` |
| 4 | Verify Connection | Polls `/api/onboarding/verify` every 3s, animated spinner, success animation | Sets `onboarding_completed = true` |

### Navigation
- Back/Next buttons at bottom
- Back returns to previous step
- Next validates current step before advancing
- Progress indicator (5 dots) at top, completed steps are clickable
- "Skip" available on step 1 (invite team)

### Animations (motion library)
- Install `motion` package (successor to framer-motion)
- Step transitions: `AnimatePresence` + horizontal slide (out-left / in-right, reverse on back)
- Progress bar: animated width transition
- Form fields: staggered fade-in on each step
- Success state (step 4): scale-up + particle/confetti effect
- Button hover/press: scale micro-interactions
- Overall: smooth, polished, Linear-quality feel

### Logo Assets
- Located at `/Users/thakurg/Hive/Research/vex-assets/`
- Wizard header: `vex-icon-dark.svg` / `vex-icon-light.svg` (V icon)
- SVG variants: horizontal, stacked, icon (dark/light/transparent)
- Copy to `public/` as part of implementation

## Part 4: Verify Connection Endpoint

### `app/api/onboarding/verify/route.ts`
- GET endpoint, authenticated
- Queries `executions` table for any row matching `org_id`
- Returns `{ connected: boolean, agent_id?: string, execution_count?: number }`
- Frontend polls every 3s
- On success → sets `onboarding_completed = true`, shows success animation

## Part 5: Documentation Page (Post-Onboarding Reference)

### Route: `/home/[account]/docs`
After onboarding, accessible from sidebar under "Getting Started" nav group.

Contains deeper reference documentation:
- Integration patterns (watch decorator, trace context, run wrapper)
- Multi-turn sessions
- Sync verification
- Correction cascade
- Error handling (AgentGuardBlockError)
- Confidence thresholds
- Full example

Note: The wizard's Step 3-4 covers basic setup. The docs page is for advanced features.

## File Summary

| Category | Files |
|----------|-------|
| **Delete** | `app/(marketing)/` — entire directory (45 files) |
| **New** | `app/onboarding/layout.tsx`, `page.tsx`, `_components/` (wizard steps, progress, animations) |
| **New** | `app/api/onboarding/verify/route.ts` |
| **New** | `app/home/[account]/docs/page.tsx`, `_components/docs-content.tsx` |
| **New** | Migration `007_onboarding_state.sql` |
| **New** | `lib/agentguard/onboarding.loader.ts` |
| **Modify** | `app/page.tsx` — root redirect |
| **Modify** | `app/home/[account]/layout.tsx` — onboarding gate |
| **Modify** | `config/paths.config.ts` — add onboarding path |
| **Modify** | `agentguard.json` — i18n strings |
| **Install** | `motion` package |
| **Copy** | Vex logo SVGs to `public/` |
