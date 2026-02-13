# Add Workspace Page Design

**Date:** 2026-02-13
**Status:** Approved

## Problem

The current workspace creation flow uses a MakerKit dialog on `/home`, which creates the team account and redirects to `/home/{slug}`. The `[account]/layout.tsx` then detects incomplete onboarding and redirects to `/onboarding?account={slug}`, where step 0 redundantly asks the user to name a workspace they already named.

## Solution

Create a dedicated `/home/addworkspace` page that serves as the entry point for workspace creation. This page replaces both the MakerKit dialog and onboarding step 0, providing a seamless start to the onboarding journey.

## Flow

```
/home → click "Create Workspace" → /home/addworkspace
  → enter workspace name → createWorkspaceAction
  → MakerKit service creates team account
  → redirect to /onboarding?account={slug} (starts at step 1: Welcome)
  → steps 1–5 of onboarding wizard
  → completeOnboardingAction → redirect to /home/{slug}
```

## Approach

**Approach A (selected):** Custom server action that wraps MakerKit's `createCreateTeamAccountService()`. Gives full control over the redirect destination, reuses the proven service layer, and keeps MakerKit packages untouched.

## Route Placement

`app/home/addworkspace/` — sits alongside `(user)/` and `[account]/` under `app/home/`. Does not inherit the `(user)` sidebar layout. Auth is handled explicitly via `requireUser` (same pattern as `/onboarding`).

## New Files

### 1. `app/home/addworkspace/page.tsx`
Server component. Checks authentication via `requireUser`. Renders the `CreateWorkspaceForm` client component in a full-screen centered layout.

### 2. `app/home/addworkspace/layout.tsx`
Minimal layout with `withI18n` wrapper. No sidebar or header.

### 3. `app/home/addworkspace/_components/create-workspace-form.tsx`
Client component matching the onboarding visual style:
- Vex logo (dark/light mode)
- Framer Motion animations
- Centered card with single name input
- "Continue" button
- Calls `createWorkspaceAction` on submit

### 4. `app/home/addworkspace/_lib/server-actions.ts`
`createWorkspaceAction`:
- Validates name via `TeamNameSchema` from MakerKit
- Generates slug from name (lowercase, hyphenated)
- Runs MakerKit policy check (`createAccountCreationPolicyEvaluator`)
- Calls `createCreateTeamAccountService().createNewOrganizationAccount()`
- Handles `duplicate_slug` error
- On success: `redirect('/onboarding?account={slug}')`

## Changes to Existing Code

### Onboarding Wizard
- Remove step 0 (`StepWorkspaceName`) from `onboarding-wizard.tsx`
- `TOTAL_STEPS` changes from 6 to 5
- Step numbering shifts: Welcome becomes step 0, Invite becomes step 1, etc.
- Delete `step-workspace-name.tsx` component

### Onboarding Server Actions
- Remove `updateWorkspaceNameAction` (no longer needed in onboarding)

### Home Page
- Replace `HomeAddAccountButton` behavior: instead of opening `CreateTeamAccountDialog`, navigate to `/home/addworkspace`
- Remove the dialog import

### Onboarding State
- Update `onboarding.loader.ts` — new accounts start at step 0 (which is now Welcome, previously step 1)
- Update DB migration defaults if needed (new accounts: `onboarding_step = 0`, `onboarding_completed = false`)

### [account] Layout
- Onboarding redirect logic in `[account]/layout.tsx` stays the same — still redirects to `/onboarding?account={slug}` when `onboarding_completed = false`

## UI Design

The `/home/addworkspace` page uses the same visual language as the onboarding wizard:
- Full-screen centered layout (no sidebar/header)
- Vex logo at top
- Heading: "Name your workspace"
- Description: brief context
- Single text input for workspace name
- "Continue" button (disabled until name is entered)
- Framer Motion fade/slide animations

## i18n

Add keys to `public/locales/en/agentguard.json` under `addWorkspace`:
- `title`: "Name your workspace"
- `description`: context text
- `placeholder`: "e.g. Acme Corp"
- `continue`: "Continue"
- `error.duplicate`: "A workspace with this name already exists"
- `error.generic`: "Failed to create workspace"
