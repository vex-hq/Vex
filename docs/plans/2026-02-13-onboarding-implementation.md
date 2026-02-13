# Onboarding Flow + Marketing Removal Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Linear-style full-screen onboarding wizard for new organizations and remove all marketing pages, redirecting unauthenticated users to `/auth/sign-in`.

**Architecture:** Dedicated `/onboarding` route with full-screen wizard (5 steps: workspace name, invite team, create API key, install SDK, verify connection). Team account layout gates dashboard access via `onboarding_completed` column on `organizations`. Marketing pages deleted, root URL redirects based on auth state. Motion library for smooth step transitions.

**Tech Stack:** Next.js 16 (App Router), React 19, TypeScript, motion (animation), Tailwind CSS, shadcn/ui, PostgreSQL (Alembic migrations)

---

### Task 1: Install motion package

**Files:**
- Modify: `nextjs-application/package.json` (root workspace)

**Step 1: Install motion**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard/nextjs-application
pnpm add motion --filter web
```

**Step 2: Verify installation**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard/nextjs-application
node -e "require('motion')" && echo "OK"
```

Expected: `OK`

**Step 3: Commit**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard
git add nextjs-application/apps/web/package.json nextjs-application/pnpm-lock.yaml
git commit -m "chore: install motion for onboarding animations"
```

---

### Task 2: Database migration — onboarding columns

**Files:**
- Create: `services/migrations/alembic/versions/008_onboarding_state.py`

**Step 1: Create migration file**

```python
"""Add onboarding state columns to organizations.

Revision ID: 008
Revises: 007
Create Date: 2026-02-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "onboarding_completed",
            sa.Boolean,
            server_default="false",
            nullable=False,
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "onboarding_step",
            sa.Integer,
            server_default="0",
            nullable=False,
        ),
    )

    # Mark all existing organizations as onboarded so they are not blocked
    op.execute("UPDATE organizations SET onboarding_completed = TRUE")


def downgrade() -> None:
    op.drop_column("organizations", "onboarding_step")
    op.drop_column("organizations", "onboarding_completed")
```

**Step 2: Run migration**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard/services/migrations
source venv/bin/activate
alembic upgrade head
```

Expected: `INFO  [alembic.runtime.migration] Running upgrade 007 -> 008, Add onboarding state columns`

**Step 3: Verify columns exist**

```bash
docker exec -it agentguard-timescaledb psql -U agentguard -d agentguard -c "\d organizations"
```

Expected: `onboarding_completed` (boolean, default false) and `onboarding_step` (integer, default 0) columns present.

**Step 4: Commit**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard
git add services/migrations/alembic/versions/008_onboarding_state.py
git commit -m "feat: migration 008 — add onboarding_completed and onboarding_step to organizations"
```

---

### Task 3: Delete marketing pages + root redirect

**Files:**
- Delete: `nextjs-application/apps/web/app/(marketing)/` (entire directory)
- Create: `nextjs-application/apps/web/app/page.tsx`

**Step 1: Delete marketing directory**

```bash
rm -rf /Users/thakurg/Hive/Research/AgentGuard/nextjs-application/apps/web/app/\(marketing\)/
```

**Step 2: Create root redirect page**

Create `nextjs-application/apps/web/app/page.tsx`:

```tsx
import { redirect } from 'next/navigation';

import { requireUser } from '@kit/supabase/require-user';
import { getSupabaseServerClient } from '@kit/supabase/server-client';

export default async function RootPage() {
  const client = getSupabaseServerClient();
  const user = await requireUser(client, { verifyMfa: false });

  if (user.data) {
    redirect('/home');
  }

  redirect('/auth/sign-in');
}
```

**Step 3: Verify typecheck**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard/nextjs-application
pnpm typecheck
```

Expected: There may be broken imports referencing marketing components. Fix any compilation errors. Common issues:
- `~/(marketing)/_components/` imports in other files — search and remove
- Any CMS/blog references — they should all be contained in the deleted directory

**Step 4: Commit**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard
git add -A
git commit -m "feat: remove marketing pages, root URL redirects to /auth/sign-in or /home"
```

---

### Task 4: Onboarding loader + path config

**Files:**
- Create: `nextjs-application/apps/web/lib/agentguard/onboarding.loader.ts`
- Modify: `nextjs-application/apps/web/config/paths.config.ts`

**Step 1: Create onboarding loader**

Create `nextjs-application/apps/web/lib/agentguard/onboarding.loader.ts`:

```typescript
import 'server-only';

import { cache } from 'react';

import { getAgentGuardPool } from '~/lib/agentguard/db';

export interface OnboardingState {
  completed: boolean;
  currentStep: number;
}

/**
 * Load onboarding state for an organization.
 *
 * Returns { completed: true, currentStep: 0 } if the org is not found
 * (treat unknown orgs as onboarded to avoid blocking).
 */
export const loadOnboardingState = cache(
  async (orgId: string): Promise<OnboardingState> => {
    const pool = getAgentGuardPool();

    const result = await pool.query<{
      onboarding_completed: boolean;
      onboarding_step: number;
    }>(
      `SELECT onboarding_completed, onboarding_step
       FROM organizations WHERE org_id = $1`,
      [orgId],
    );

    if (!result.rows.length) {
      return { completed: true, currentStep: 0 };
    }

    return {
      completed: result.rows[0]!.onboarding_completed,
      currentStep: result.rows[0]!.onboarding_step,
    };
  },
);

/**
 * Update onboarding progress for an organization.
 */
export async function updateOnboardingStep(
  orgId: string,
  step: number,
): Promise<void> {
  const pool = getAgentGuardPool();

  await pool.query(
    `UPDATE organizations
     SET onboarding_step = $2, updated_at = NOW()
     WHERE org_id = $1`,
    [orgId, step],
  );
}

/**
 * Mark onboarding as completed for an organization.
 */
export async function completeOnboarding(orgId: string): Promise<void> {
  const pool = getAgentGuardPool();

  await pool.query(
    `UPDATE organizations
     SET onboarding_completed = TRUE, onboarding_step = 5, updated_at = NOW()
     WHERE org_id = $1`,
    [orgId],
  );
}
```

**Step 2: Add onboarding path to paths config**

In `nextjs-application/apps/web/config/paths.config.ts`:

Add to the Zod schema:
```typescript
accountOnboarding: z.string().min(1),
```

Add to the config object:
```typescript
accountOnboarding: '/onboarding',
```

**Step 3: Typecheck**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard/nextjs-application
pnpm typecheck
```

**Step 4: Commit**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard
git add nextjs-application/apps/web/lib/agentguard/onboarding.loader.ts nextjs-application/apps/web/config/paths.config.ts
git commit -m "feat: onboarding loader + path config for /onboarding route"
```

---

### Task 5: Onboarding gate in team account layout

**Files:**
- Modify: `nextjs-application/apps/web/app/home/[account]/layout.tsx`

**Step 1: Add onboarding redirect to SidebarLayout**

In `nextjs-application/apps/web/app/home/[account]/layout.tsx`, import the onboarding loader and `resolveOrgId`, then add a check in `SidebarLayout` (the primary layout) after loading workspace data.

Add imports at the top:
```typescript
import { loadOnboardingState } from '~/lib/agentguard/onboarding.loader';
import { resolveOrgId } from '~/lib/agentguard/resolve-org-id';
```

In `SidebarLayout`, after `loadTeamWorkspace(account)` resolves and before rendering, add:
```typescript
const orgId = await resolveOrgId(account);
const onboarding = await loadOnboardingState(orgId);

if (!onboarding.completed) {
  redirect(`/onboarding?account=${account}`);
}
```

Do the same in `HeaderLayout`.

**Step 2: Typecheck**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard/nextjs-application
pnpm typecheck
```

**Step 3: Commit**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard
git add nextjs-application/apps/web/app/home/\\[account\\]/layout.tsx
git commit -m "feat: gate team dashboard behind onboarding completion"
```

---

### Task 6: Copy logo assets to public directory

**Files:**
- Copy: SVG logos from `/Users/thakurg/Hive/Research/vex-assets/svg/` to `nextjs-application/apps/web/public/images/`

**Step 1: Copy logo files**

```bash
cp /Users/thakurg/Hive/Research/vex-assets/svg/vex-icon-dark.svg /Users/thakurg/Hive/Research/AgentGuard/nextjs-application/apps/web/public/images/
cp /Users/thakurg/Hive/Research/vex-assets/svg/vex-icon-light.svg /Users/thakurg/Hive/Research/AgentGuard/nextjs-application/apps/web/public/images/
cp /Users/thakurg/Hive/Research/vex-assets/svg/vex-stacked-dark.svg /Users/thakurg/Hive/Research/AgentGuard/nextjs-application/apps/web/public/images/
cp /Users/thakurg/Hive/Research/vex-assets/svg/vex-stacked-light.svg /Users/thakurg/Hive/Research/AgentGuard/nextjs-application/apps/web/public/images/
```

**Step 2: Verify files accessible**

```bash
ls -la /Users/thakurg/Hive/Research/AgentGuard/nextjs-application/apps/web/public/images/vex-*
```

Expected: 4 SVG files present.

**Step 3: Commit**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard
git add nextjs-application/apps/web/public/images/vex-*.svg
git commit -m "chore: add Vex logo assets for onboarding wizard"
```

---

### Task 7: Add i18n strings for onboarding

**Files:**
- Modify: `nextjs-application/apps/web/public/locales/en/agentguard.json`

**Step 1: Add onboarding namespace**

Add a new top-level `"onboarding"` key to `agentguard.json`:

```json
"onboarding": {
  "pageTitle": "Set Up Your Workspace",
  "step1Title": "Name Your Workspace",
  "step1Description": "Give your workspace a name that your team will recognize.",
  "step1Placeholder": "e.g., Acme AI Team",
  "step2Title": "Invite Your Team",
  "step2Description": "Add team members by email. You can always invite more later.",
  "step2Placeholder": "colleague@company.com",
  "step2AddAnother": "Add another",
  "step2Skip": "Skip for now",
  "step2RoleAdmin": "Admin",
  "step2RoleMember": "Member",
  "step3Title": "Your API Key",
  "step3Description": "Use this key to authenticate your agents with Vex. Copy it now — you won't see it again.",
  "step3Warning": "This key is shown only once. Store it securely.",
  "step3Copied": "Copied!",
  "step3CopyKey": "Copy Key",
  "step4Title": "Install the SDK",
  "step4Description": "Add the Vex SDK to your Python project and initialize it with your API key.",
  "step4InstallTitle": "Install",
  "step4InitTitle": "Initialize",
  "step5Title": "Verify Connection",
  "step5Description": "Run your agent with the SDK initialized. We're listening for your first event.",
  "step5Waiting": "Waiting for your first event...",
  "step5Connected": "Connected!",
  "step5AgentDetected": "Agent detected: {{agentId}}",
  "step5Executions": "{{count}} execution(s) received",
  "next": "Continue",
  "back": "Back",
  "finish": "Go to Dashboard",
  "stepOf": "Step {{current}} of {{total}}"
}
```

**Step 2: Commit**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard
git add nextjs-application/apps/web/public/locales/en/agentguard.json
git commit -m "feat: add onboarding i18n strings"
```

---

### Task 8: Onboarding server actions

**Files:**
- Create: `nextjs-application/apps/web/app/onboarding/_lib/server/onboarding-actions.ts`

**Step 1: Create server actions**

These server actions handle the mutation side of each onboarding step.

```typescript
'use server';

import { z } from 'zod';

import { enhanceAction } from '@kit/next/actions';
import { requireUser } from '@kit/supabase/require-user';
import { getSupabaseServerClient } from '@kit/supabase/server-client';

import { createKey } from '~/lib/agentguard/api-keys';
import {
  completeOnboarding,
  updateOnboardingStep,
} from '~/lib/agentguard/onboarding.loader';
import { resolveOrgId } from '~/lib/agentguard/resolve-org-id';

// --- Step 1: Update workspace name ---
const UpdateNameSchema = z.object({
  accountSlug: z.string().min(1),
  name: z.string().min(1).max(100),
});

export const updateWorkspaceName = enhanceAction(
  async (data) => {
    const client = getSupabaseServerClient();
    const { data: user } = await requireUser(client);

    if (!user) throw new Error('Not authenticated');

    const orgId = await resolveOrgId(data.accountSlug);
    const { getAgentGuardPool } = await import('~/lib/agentguard/db');
    const pool = getAgentGuardPool();

    await pool.query(
      `UPDATE organizations SET name = $2, updated_at = NOW() WHERE org_id = $1`,
      [orgId, data.name],
    );

    await updateOnboardingStep(orgId, 1);

    return { success: true };
  },
  { schema: UpdateNameSchema },
);

// --- Step 2: Save step progress (invite is handled by existing MakerKit) ---
const SaveStepSchema = z.object({
  accountSlug: z.string().min(1),
  step: z.number().min(0).max(5),
});

export const saveOnboardingStep = enhanceAction(
  async (data) => {
    const client = getSupabaseServerClient();
    const { data: user } = await requireUser(client);

    if (!user) throw new Error('Not authenticated');

    const orgId = await resolveOrgId(data.accountSlug);
    await updateOnboardingStep(orgId, data.step);

    return { success: true };
  },
  { schema: SaveStepSchema },
);

// --- Step 3: Create API key ---
const CreateKeySchema = z.object({
  accountSlug: z.string().min(1),
});

export const createOnboardingKey = enhanceAction(
  async (data) => {
    const client = getSupabaseServerClient();
    const { data: user } = await requireUser(client);

    if (!user) throw new Error('Not authenticated');

    const orgId = await resolveOrgId(data.accountSlug);

    const result = await createKey({
      orgId,
      name: 'Default Key',
      scopes: ['ingest', 'verify', 'read'],
      rateLimitRpm: 1000,
      expiresAt: null,
      createdBy: user.id,
    });

    await updateOnboardingStep(orgId, 3);

    return { key: result.key };
  },
  { schema: CreateKeySchema },
);

// --- Step 5: Complete onboarding ---
const CompleteSchema = z.object({
  accountSlug: z.string().min(1),
});

export const completeOnboardingAction = enhanceAction(
  async (data) => {
    const client = getSupabaseServerClient();
    const { data: user } = await requireUser(client);

    if (!user) throw new Error('Not authenticated');

    const orgId = await resolveOrgId(data.accountSlug);
    await completeOnboarding(orgId);

    return { success: true };
  },
  { schema: CompleteSchema },
);
```

**Step 2: Typecheck**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard/nextjs-application
pnpm typecheck
```

**Step 3: Commit**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard
git add nextjs-application/apps/web/app/onboarding/_lib/server/onboarding-actions.ts
git commit -m "feat: onboarding server actions (workspace name, step progress, API key, complete)"
```

---

### Task 9: Verify connection API endpoint

**Files:**
- Create: `nextjs-application/apps/web/app/api/onboarding/verify/route.ts`

**Step 1: Create the verify endpoint**

```typescript
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

import { requireUser } from '@kit/supabase/require-user';
import { getSupabaseServerClient } from '@kit/supabase/server-client';

import { getAgentGuardPool } from '~/lib/agentguard/db';
import { resolveOrgId } from '~/lib/agentguard/resolve-org-id';

export async function GET(request: NextRequest) {
  const client = getSupabaseServerClient();
  const { data: user } = await requireUser(client);

  if (!user) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const accountSlug = request.nextUrl.searchParams.get('account');

  if (!accountSlug) {
    return NextResponse.json(
      { error: 'Missing account parameter' },
      { status: 400 },
    );
  }

  const orgId = await resolveOrgId(accountSlug);
  const pool = getAgentGuardPool();

  const result = await pool.query<{
    agent_id: string;
    execution_count: string;
  }>(
    `SELECT agent_id, COUNT(*) AS execution_count
     FROM executions
     WHERE org_id = $1
     GROUP BY agent_id
     ORDER BY MAX(timestamp) DESC
     LIMIT 1`,
    [orgId],
  );

  if (!result.rows.length) {
    return NextResponse.json({ connected: false });
  }

  return NextResponse.json({
    connected: true,
    agentId: result.rows[0]!.agent_id,
    executionCount: parseInt(result.rows[0]!.execution_count, 10),
  });
}
```

**Step 2: Typecheck**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard/nextjs-application
pnpm typecheck
```

**Step 3: Commit**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard
git add nextjs-application/apps/web/app/api/onboarding/verify/route.ts
git commit -m "feat: GET /api/onboarding/verify — polls for first execution event"
```

---

### Task 10: Onboarding wizard — layout and page

**Files:**
- Create: `nextjs-application/apps/web/app/onboarding/layout.tsx`
- Create: `nextjs-application/apps/web/app/onboarding/page.tsx`

**Step 1: Create onboarding layout**

`nextjs-application/apps/web/app/onboarding/layout.tsx`:

```tsx
import { withI18n } from '~/lib/i18n/with-i18n';

function OnboardingLayout({ children }: React.PropsWithChildren) {
  return (
    <div className="bg-background flex min-h-screen items-center justify-center">
      {children}
    </div>
  );
}

export default withI18n(OnboardingLayout);
```

**Step 2: Create onboarding page (server component)**

`nextjs-application/apps/web/app/onboarding/page.tsx`:

```tsx
import { redirect } from 'next/navigation';

import { requireUser } from '@kit/supabase/require-user';
import { getSupabaseServerClient } from '@kit/supabase/server-client';

import { loadOnboardingState } from '~/lib/agentguard/onboarding.loader';
import { resolveOrgId } from '~/lib/agentguard/resolve-org-id';

import { OnboardingWizard } from './_components/onboarding-wizard';

interface OnboardingPageProps {
  searchParams: Promise<{ account?: string }>;
}

export default async function OnboardingPage(props: OnboardingPageProps) {
  const client = getSupabaseServerClient();
  const { data: user } = await requireUser(client);

  if (!user) {
    redirect('/auth/sign-in');
  }

  const { account } = await props.searchParams;

  if (!account) {
    redirect('/home');
  }

  const orgId = await resolveOrgId(account);
  const onboarding = await loadOnboardingState(orgId);

  if (onboarding.completed) {
    redirect(`/home/${account}`);
  }

  return (
    <OnboardingWizard
      accountSlug={account}
      initialStep={onboarding.currentStep}
    />
  );
}
```

**Step 3: Typecheck**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard/nextjs-application
pnpm typecheck
```

Note: This will fail until Task 11 creates the `OnboardingWizard` component. That's expected — proceed to Task 11.

**Step 4: Commit (after Task 11)**

Combined with Task 11 commit.

---

### Task 11: Onboarding wizard — client component

**Files:**
- Create: `nextjs-application/apps/web/app/onboarding/_components/onboarding-wizard.tsx`
- Create: `nextjs-application/apps/web/app/onboarding/_components/steps/step-workspace-name.tsx`
- Create: `nextjs-application/apps/web/app/onboarding/_components/steps/step-invite-team.tsx`
- Create: `nextjs-application/apps/web/app/onboarding/_components/steps/step-api-key.tsx`
- Create: `nextjs-application/apps/web/app/onboarding/_components/steps/step-install-sdk.tsx`
- Create: `nextjs-application/apps/web/app/onboarding/_components/steps/step-verify-connection.tsx`
- Create: `nextjs-application/apps/web/app/onboarding/_components/progress-dots.tsx`
- Create: `nextjs-application/apps/web/app/onboarding/_components/code-block.tsx`

This is the largest task. Each step is a separate component, orchestrated by the wizard container.

**Step 1: Create the wizard container**

`onboarding-wizard.tsx` — The main orchestrator. Uses `motion` for animated step transitions, manages step state, renders the current step with `AnimatePresence`.

Key implementation details:
- `'use client'` component
- State: `currentStep` (number 0-4), `direction` (1 or -1 for slide direction)
- `AnimatePresence` wraps the active step
- Each step gets `onNext()` and `onBack()` callbacks
- Progress dots at top show completion state
- Logo (V icon) centered above progress dots
- Back/Next buttons at bottom (Next is disabled until step validates)
- Slide animation: `x: direction * 300` initial, `x: 0` animate, `x: direction * -300` exit

**Step 2: Create each step component**

Each step is a `'use client'` component with:
- Props: `accountSlug`, `onNext()`, `onBack()` (optional for step 0)
- Internal form state
- Server action call on submit
- Staggered `motion.div` fade-in for child elements

See the design doc for the content of each step:
- **Step 0 (Workspace Name):** Text input, validates non-empty, calls `updateWorkspaceName`
- **Step 1 (Invite Team):** Dynamic email list, role selector per email, "Skip" button, calls MakerKit invite or just calls `saveOnboardingStep`
- **Step 2 (API Key):** Auto-generates on mount via `createOnboardingKey`, shows key with copy button, "shown once" warning badge
- **Step 3 (Install SDK):** Static code snippets with copy buttons: `pip install agentx-sdk` and initialization code with the API key from step 2 pre-filled
- **Step 4 (Verify Connection):** Polls `/api/onboarding/verify?account=X` every 3s via `useEffect` + `setInterval`, shows animated spinner while waiting, success animation when connected, calls `completeOnboardingAction`

**Step 3: Create the progress dots component**

`progress-dots.tsx` — 5 circles in a row, filled for completed steps, outlined+pulsing for current, dimmed for future. Clickable for completed steps. Uses `motion.div` for scale animation on state change.

**Step 4: Create the code block component**

`code-block.tsx` — Reusable code block with copy-to-clipboard button. `<pre><code>` with monospace font, dark background, copy icon in top-right corner that changes to checkmark on click.

**Step 5: Typecheck, lint, format**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard/nextjs-application
pnpm typecheck && pnpm lint:fix && pnpm format:fix
```

**Step 6: Commit**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard
git add nextjs-application/apps/web/app/onboarding/
git commit -m "feat: full-screen onboarding wizard with 5 steps and motion animations"
```

---

### Task 12: Documentation page (post-onboarding reference)

**Files:**
- Create: `nextjs-application/apps/web/app/home/[account]/docs/page.tsx`
- Create: `nextjs-application/apps/web/app/home/[account]/docs/_components/docs-content.tsx`

**Step 1: Create docs page (server component)**

`page.tsx` — Standard MakerKit page pattern with `withI18n()`, `generateMetadata`, `TeamAccountLayoutPageHeader`, `PageBody`. No data fetching — purely static documentation content. Renders `<DocsContent accountSlug={account} />`.

**Step 2: Create docs content (client component)**

`docs-content.tsx` — `'use client'` component with all SDK documentation sections using Cards. Reuses the `CodeBlock` component from onboarding. Contains sections for:
1. Installation (`pip install agentx-sdk`)
2. Quick Start (watch decorator example)
3. Configuration (GuardConfig options table)
4. Integration Patterns (tabs: watch / trace / run)
5. Multi-Turn Sessions
6. Sync Verification
7. Correction Cascade
8. Error Handling (AgentGuardBlockError)
9. Confidence Thresholds
10. Full Example

Each section is a Card with CardHeader + CardContent. Code blocks have copy buttons. Links to API Keys page for key management.

**Step 3: Typecheck, lint, format**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard/nextjs-application
pnpm typecheck && pnpm lint:fix && pnpm format:fix
```

**Step 4: Commit**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard
git add nextjs-application/apps/web/app/home/\\[account\\]/docs/
git commit -m "feat: SDK documentation page at /home/[account]/docs"
```

---

### Task 13: Update auto-provision to set onboarding_completed = false

**Files:**
- Modify: `nextjs-application/apps/web/lib/agentguard/resolve-org-id.ts`

**Step 1: Update INSERT to set onboarding_completed = false**

In the auto-provision `INSERT` query in `resolve-org-id.ts`, add `onboarding_completed` and `onboarding_step` columns:

Change the INSERT from:
```sql
INSERT INTO organizations (org_id, name, api_keys, plan, account_slug)
VALUES ($1, $2, '[]'::jsonb, 'free', $3)
ON CONFLICT (org_id) DO UPDATE SET account_slug = EXCLUDED.account_slug
```

To:
```sql
INSERT INTO organizations (org_id, name, api_keys, plan, account_slug, onboarding_completed, onboarding_step)
VALUES ($1, $2, '[]'::jsonb, 'free', $3, FALSE, 0)
ON CONFLICT (org_id) DO UPDATE SET account_slug = EXCLUDED.account_slug
```

This ensures newly auto-provisioned orgs get `onboarding_completed = false` so they are redirected to the wizard.

**Step 2: Typecheck**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard/nextjs-application
pnpm typecheck
```

**Step 3: Commit**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard
git add nextjs-application/apps/web/lib/agentguard/resolve-org-id.ts
git commit -m "feat: auto-provisioned orgs start with onboarding_completed = false"
```

---

### Task 14: Typecheck, lint, format — final verification

**Step 1: Full build check**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard/nextjs-application
pnpm typecheck && pnpm lint:fix && pnpm format:fix
```

Fix any remaining issues.

**Step 2: Commit any fixes**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard
git add -A
git commit -m "fix: lint and format cleanup for onboarding"
```

---

### Task 15: Live test

**Step 1: Start dev server**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard/nextjs-application
pnpm dev
```

**Step 2: Test root redirect**

- Navigate to `http://localhost:3001/` — should redirect to `/auth/sign-in`
- Sign in → should redirect to `/home`

**Step 3: Test onboarding flow**

- Create a new team account (or use one that hasn't completed onboarding)
- Navigate to team dashboard → should redirect to `/onboarding?account=<slug>`
- Step 1: Enter workspace name → Continue
- Step 2: Skip (or add emails) → Continue
- Step 3: API key auto-generated → Copy → Continue
- Step 4: See SDK install instructions → Continue
- Step 5: See "Waiting for first event..." (can skip by manually calling `completeOnboardingAction` or running demo agent with the generated key)
- After completion → redirects to team dashboard

**Step 4: Test existing org not blocked**

- Navigate to existing org (`/home/makerkit`) — should load dashboard directly (no onboarding redirect since migration set `onboarding_completed = true`)

**Step 5: Test docs page**

- Navigate to `/home/makerkit/docs` — should show documentation page
- Verify all code blocks render, copy buttons work

**Step 6: Fix any issues found during testing**

If issues found, fix and commit.
