# Add Workspace Page Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a dedicated `/home/addworkspace` page that replaces the MakerKit dialog and onboarding step 0, serving as the workspace creation entry point that flows directly into the onboarding wizard.

**Architecture:** New route at `app/home/addworkspace/` with a server action wrapping MakerKit's `createCreateTeamAccountService()`. The onboarding wizard drops step 0 and renumbers steps 1-5 to 0-4. The "Create Team" button on `/home` becomes a navigation link to `/home/addworkspace`.

**Tech Stack:** Next.js 16 (App Router), React 19, Framer Motion, Zod, MakerKit team-accounts service, i18n via react-i18next

---

### Task 1: Create the server action for workspace creation

**Files:**
- Create: `apps/web/app/home/addworkspace/_lib/server-actions.ts`

**Step 1: Write the server action**

Create `apps/web/app/home/addworkspace/_lib/server-actions.ts`:

```typescript
'use server';

import { redirect } from 'next/navigation';

import { z } from 'zod';

import { enhanceAction } from '@kit/next/actions';
import { getLogger } from '@kit/shared/logger';
import { TeamNameSchema } from '@kit/team-accounts/schema';

import { createAccountCreationPolicyEvaluator } from '../../../../../../packages/features/team-accounts/src/server/policies';
import { createCreateTeamAccountService } from '../../../../../../packages/features/team-accounts/src/server/services/create-team-account.service';

const CreateWorkspaceSchema = z.object({
  name: TeamNameSchema,
});

export const createWorkspaceAction = enhanceAction(
  async ({ name }, user) => {
    const logger = await getLogger();

    const ctx = {
      name: 'workspace.create',
      userId: user.id,
      workspaceName: name,
    };

    logger.info(ctx, 'Creating workspace...');

    // Check policies
    const evaluator = createAccountCreationPolicyEvaluator();

    if (await evaluator.hasPoliciesForStage('submission')) {
      const policyContext = {
        timestamp: new Date().toISOString(),
        userId: user.id,
        accountName: name,
      };

      const result = await evaluator.canCreateAccount(
        policyContext,
        'submission',
      );

      if (!result.allowed) {
        logger.warn(
          { ...ctx, reasons: result.reasons },
          'Policy denied workspace creation',
        );

        return {
          error: true as const,
          message: result.reasons[0] ?? 'Policy denied workspace creation',
        };
      }
    }

    // Generate slug from name
    const slug = name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '');

    const service = createCreateTeamAccountService();

    const { data, error } = await service.createNewOrganizationAccount({
      name,
      userId: user.id,
      slug,
    });

    if (error === 'duplicate_slug') {
      return {
        error: true as const,
        message: 'teams:duplicateSlugError',
      };
    }

    logger.info(ctx, 'Workspace created');

    redirect(`/onboarding?account=${data.slug}`);
  },
  {
    schema: CreateWorkspaceSchema,
  },
);
```

**Important:** The imports for MakerKit's internal service and policies use deep paths. Check the actual export paths:
- Look at `packages/features/team-accounts/src/server/policies/index.ts` for the policy evaluator export
- Look at `packages/features/team-accounts/package.json` for the `exports` field — the service may be available via `@kit/team-accounts/server` or similar

Run: `grep -r "createAccountCreationPolicyEvaluator" packages/features/team-accounts/` to find the exact import path.
Run: `grep -r "createCreateTeamAccountService" packages/features/team-accounts/` to verify.

If these are not exported in the package.json `exports` map, use the relative deep import paths instead.

**Step 2: Commit**

```bash
git add apps/web/app/home/addworkspace/_lib/server-actions.ts
git commit -m "feat: add createWorkspaceAction server action for /home/addworkspace"
```

---

### Task 2: Create the workspace form client component

**Files:**
- Create: `apps/web/app/home/addworkspace/_components/create-workspace-form.tsx`

**Step 1: Write the form component**

This component reuses the visual style of the existing `StepWorkspaceName` (Vex logo, framer-motion animations, centered card) but calls the new `createWorkspaceAction` instead.

Create `apps/web/app/home/addworkspace/_components/create-workspace-form.tsx`:

```typescript
'use client';

import { useState, useTransition } from 'react';

import Image from 'next/image';

import { isRedirectError } from 'next/dist/client/components/redirect-error';
import { motion } from 'motion/react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription } from '@kit/ui/alert';
import { Button } from '@kit/ui/button';
import { Input } from '@kit/ui/input';
import { Label } from '@kit/ui/label';
import { Trans } from '@kit/ui/trans';

import { createWorkspaceAction } from '../_lib/server-actions';

export function CreateWorkspaceForm() {
  const { t } = useTranslation('agentguard');
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    if (!name.trim()) return;

    setError(null);

    startTransition(async () => {
      try {
        const result = await createWorkspaceAction({ name: name.trim() });

        if (result?.error) {
          setError(result.message ?? t('addWorkspace.errorGeneric'));
        }
      } catch (err) {
        if (!isRedirectError(err)) {
          setError(t('addWorkspace.errorGeneric'));
        }
      }
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-8">
      {/* V logo */}
      <motion.div
        className="flex justify-center"
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        <Image
          src="/images/vex-icon-black-transparent.svg"
          alt="Vex"
          width={120}
          height={120}
          className="block dark:hidden"
          priority
        />
        <Image
          src="/images/vex-icon-white-transparent.svg"
          alt="Vex"
          width={120}
          height={120}
          className="hidden dark:block"
          priority
        />
      </motion.div>

      {/* Heading + description */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
      >
        <h1 className="text-center text-3xl font-bold tracking-tight">
          {t('addWorkspace.title')}
        </h1>
        <p className="text-muted-foreground mx-auto mt-2 max-w-md text-center">
          {t('addWorkspace.description')}
        </p>
      </motion.div>

      {/* Error alert */}
      {error && (
        <Alert variant="destructive">
          <AlertDescription>
            <Trans i18nKey={error} defaults={error} />
          </AlertDescription>
        </Alert>
      )}

      {/* Card with input */}
      <motion.div
        className="border-border/50 bg-card/50 rounded-xl border p-6 md:p-8"
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
      >
        <Label htmlFor="workspace-name" className="sr-only">
          {t('addWorkspace.title')}
        </Label>
        <Input
          id="workspace-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t('addWorkspace.placeholder')}
          autoFocus
          className="h-12 text-lg"
          minLength={2}
          maxLength={50}
        />
      </motion.div>

      {/* CTA button */}
      <motion.div
        className="flex justify-center"
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
      >
        <Button
          type="submit"
          disabled={!name.trim() || pending}
          className="rounded-lg px-8"
          size="lg"
        >
          {pending ? t('addWorkspace.creating') : t('addWorkspace.continue')}
        </Button>
      </motion.div>
    </form>
  );
}
```

**Step 2: Commit**

```bash
git add apps/web/app/home/addworkspace/_components/create-workspace-form.tsx
git commit -m "feat: add CreateWorkspaceForm client component"
```

---

### Task 3: Create the addworkspace page and layout

**Files:**
- Create: `apps/web/app/home/addworkspace/page.tsx`
- Create: `apps/web/app/home/addworkspace/layout.tsx`

**Step 1: Write the layout**

Create `apps/web/app/home/addworkspace/layout.tsx`:

```typescript
import { Toaster } from '@kit/ui/sonner';

export default function AddWorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="bg-background min-h-screen">
      {children}
      <Toaster />
    </div>
  );
}
```

This mirrors the onboarding layout — minimal wrapper, no sidebar/header.

**Step 2: Write the page**

Create `apps/web/app/home/addworkspace/page.tsx`:

```typescript
import { redirect } from 'next/navigation';

import { requireUser } from '@kit/supabase/require-user';
import { getSupabaseServerClient } from '@kit/supabase/server-client';

import { withI18n } from '~/lib/i18n/with-i18n';

import { CreateWorkspaceForm } from './_components/create-workspace-form';

async function AddWorkspacePage() {
  const client = getSupabaseServerClient();
  const { data: user } = await requireUser(client);

  if (!user) {
    redirect('/auth/sign-in');
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-4">
      <div className="w-full max-w-xl">
        <CreateWorkspaceForm />
      </div>
    </div>
  );
}

export default withI18n(AddWorkspacePage);
```

**Step 3: Verify the page loads**

Run the dev server and navigate to `http://localhost:3000/home/addworkspace`. Verify:
- Auth redirect works (unauthenticated → `/auth/sign-in`)
- Authenticated users see the workspace name form
- No sidebar or header visible

**Step 4: Commit**

```bash
git add apps/web/app/home/addworkspace/page.tsx apps/web/app/home/addworkspace/layout.tsx
git commit -m "feat: add /home/addworkspace page and layout"
```

---

### Task 4: Add i18n keys for addWorkspace

**Files:**
- Modify: `apps/web/public/locales/en/agentguard.json`

**Step 1: Add the i18n keys**

Add a new `"addWorkspace"` section to `agentguard.json` (after the `"onboarding"` section, before `"common"`):

```json
"addWorkspace": {
  "title": "Name Your Workspace",
  "description": "Create a workspace where your team will monitor, verify, and secure your AI agents.",
  "placeholder": "e.g., Acme AI Ops",
  "continue": "Continue",
  "creating": "Creating...",
  "errorDuplicate": "A workspace with this name already exists. Try a different name.",
  "errorGeneric": "Failed to create workspace. Please try again."
},
```

**Step 2: Commit**

```bash
git add apps/web/public/locales/en/agentguard.json
git commit -m "feat: add i18n keys for addWorkspace page"
```

---

### Task 5: Update HomeAddAccountButton to navigate instead of opening dialog

**Files:**
- Modify: `apps/web/app/home/(user)/_components/home-add-account-button.tsx`

**Step 1: Replace the dialog with navigation**

Replace the entire content of `home-add-account-button.tsx`:

```typescript
'use client';

import Link from 'next/link';

import { Button } from '@kit/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@kit/ui/tooltip';
import { Trans } from '@kit/ui/trans';

interface HomeAddAccountButtonProps {
  className?: string;
  canCreateTeamAccount?: {
    allowed: boolean;
    reason?: string;
  };
}

export function HomeAddAccountButton(props: HomeAddAccountButtonProps) {
  const canCreate = props.canCreateTeamAccount?.allowed ?? true;
  const reason = props.canCreateTeamAccount?.reason;

  const button = (
    <Button
      className={props.className}
      disabled={!canCreate}
      asChild={canCreate}
    >
      {canCreate ? (
        <Link href="/home/addworkspace">
          <Trans i18nKey={'account:createTeamButtonLabel'} />
        </Link>
      ) : (
        <Trans i18nKey={'account:createTeamButtonLabel'} />
      )}
    </Button>
  );

  if (!canCreate && reason) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="cursor-not-allowed">{button}</span>
          </TooltipTrigger>
          <TooltipContent>
            <Trans i18nKey={reason} defaults={reason} />
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  return button;
}
```

Key changes:
- Removed `useState`, `CreateTeamAccountDialog` imports
- Button now renders a `<Link href="/home/addworkspace">` when allowed
- Uses `asChild` prop on Button to compose with Link
- Tooltip behavior for disabled state remains unchanged

**Step 2: Verify the button navigates correctly**

Navigate to `/home`. Click "Create Team" button. It should navigate to `/home/addworkspace` instead of opening a dialog.

**Step 3: Commit**

```bash
git add apps/web/app/home/(user)/_components/home-add-account-button.tsx
git commit -m "refactor: replace CreateTeamAccountDialog with navigation to /home/addworkspace"
```

---

### Task 6: Remove step 0 from onboarding wizard and renumber steps

**Files:**
- Modify: `apps/web/app/onboarding/_components/onboarding-wizard.tsx`
- Delete: `apps/web/app/onboarding/_components/step-workspace-name.tsx`
- Modify: `apps/web/app/onboarding/_lib/server-actions.ts` (remove `updateWorkspaceNameAction`)
- Modify: `apps/web/lib/agentguard/onboarding.loader.ts` (update `completeOnboarding` step number)

**Step 1: Update the onboarding wizard**

Replace the content of `onboarding-wizard.tsx`:

```typescript
'use client';

import { useCallback, useState } from 'react';

import { AnimatePresence, motion } from 'motion/react';

import { updateOnboardingStepAction } from '../_lib/server-actions';
import { StepApiKey } from './step-api-key';
import { StepInstallSdk } from './step-install-sdk';
import { StepInviteTeam } from './step-invite-team';
import { StepVerifyConnection } from './step-verify-connection';
import { StepWelcome } from './step-welcome';

const TOTAL_STEPS = 5;

interface OnboardingWizardProps {
  accountSlug: string;
  initialStep: number;
}

export function OnboardingWizard({
  accountSlug,
  initialStep,
}: OnboardingWizardProps) {
  const [currentStep, setCurrentStep] = useState(initialStep);
  const [apiKey, setApiKey] = useState<string | null>(null);

  const goNext = useCallback(async () => {
    const nextStep = currentStep + 1;
    setCurrentStep(nextStep);

    if (nextStep < TOTAL_STEPS) {
      await updateOnboardingStepAction({
        accountSlug,
        step: nextStep,
      });
    }
  }, [currentStep, accountSlug]);

  const goBack = useCallback(() => {
    setCurrentStep((s) => Math.max(0, s - 1));
  }, []);

  const renderStep = () => {
    switch (currentStep) {
      case 0:
        return <StepWelcome key="step-0" onNext={goNext} />;
      case 1:
        return (
          <StepInviteTeam
            key="step-1"
            accountSlug={accountSlug}
            onNext={goNext}
            onBack={goBack}
          />
        );
      case 2:
        return (
          <StepApiKey
            key="step-2"
            accountSlug={accountSlug}
            onNext={goNext}
            onBack={goBack}
            onKeyCreated={setApiKey}
          />
        );
      case 3:
        return (
          <StepInstallSdk
            key="step-3"
            apiKey={apiKey}
            onNext={goNext}
            onBack={goBack}
          />
        );
      case 4:
        return (
          <StepVerifyConnection
            key="step-4"
            accountSlug={accountSlug}
            onBack={goBack}
          />
        );
      default:
        return null;
    }
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-4">
      <div className="w-full max-w-xl">
        <AnimatePresence mode="wait">
          <motion.div
            key={currentStep}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.25 }}
          >
            {renderStep()}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}
```

**Step 2: Delete step-workspace-name.tsx**

```bash
rm apps/web/app/onboarding/_components/step-workspace-name.tsx
```

**Step 3: Update onboarding server-actions.ts**

Remove `updateWorkspaceNameAction` and its schema. In `apps/web/app/onboarding/_lib/server-actions.ts`:

- Delete lines 18-21 (`UpdateWorkspaceNameSchema`)
- Delete lines 46-71 (`updateWorkspaceNameAction`)
- Update `UpdateStepSchema` max: change `.max(4)` to `.max(3)` (line 39)

The remaining actions are: `sendInvitesAction`, `createOnboardingKeyAction`, `updateOnboardingStepAction`, `completeOnboardingAction`.

Also update the step numbers in the remaining actions:
- `sendInvitesAction`: change `updateOnboardingStep(data.accountSlug, 2)` → `updateOnboardingStep(data.accountSlug, 1)`
- `createOnboardingKeyAction`: change `updateOnboardingStep(data.accountSlug, 3)` → `updateOnboardingStep(data.accountSlug, 2)`

**Step 4: Update onboarding.loader.ts**

In `apps/web/lib/agentguard/onboarding.loader.ts`, update `completeOnboarding`:

Change line 62: `onboarding_step: 5` → `onboarding_step: 4`

**Step 5: Verify onboarding flow**

Navigate to `/onboarding?account={existing-slug}`. Verify:
- Wizard starts at step 0 (Welcome), not workspace name
- All 5 steps work (Welcome → Invite → API Key → Install SDK → Verify)
- Step navigation (back/next) works correctly

**Step 6: Commit**

```bash
git add -A apps/web/app/onboarding/ apps/web/lib/agentguard/onboarding.loader.ts
git commit -m "refactor: remove step 0 from onboarding wizard, renumber steps 1-5 to 0-4"
```

---

### Task 7: End-to-end verification and cleanup

**Step 1: Test the full flow**

1. Go to `/home` (logged in)
2. Click "Create Team" button → should navigate to `/home/addworkspace`
3. Enter workspace name → submit → should redirect to `/onboarding?account={slug}`
4. Onboarding wizard starts at step 0 (Welcome), not workspace name
5. Complete all 5 steps
6. After completion, redirect to `/home/{slug}` — should load the dashboard (no onboarding redirect loop)

**Step 2: Test edge cases**

- Submit empty name → button should be disabled
- Submit duplicate slug → should show error message
- Directly visit `/home/{slug}` for new account → should redirect to `/onboarding?account={slug}`
- Resume interrupted onboarding → should resume at correct step

**Step 3: Run type checking**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard/nextjs-application && pnpm typecheck
```

**Step 4: Run linting and formatting**

```bash
cd /Users/thakurg/Hive/Research/AgentGuard/nextjs-application && pnpm lint:fix && pnpm format:fix
```

**Step 5: Final commit (if lint/format changes)**

```bash
git add -A && git commit -m "chore: lint and format fixes for addworkspace feature"
```
