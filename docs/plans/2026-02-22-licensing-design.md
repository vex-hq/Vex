# Vex Dual-License Strategy Design

**Date:** 2026-02-22
**Status:** Approved

## Goal

Split Vex into two license zones:
- **SDKs** — Apache 2.0 (zero friction for `pip install vex-sdk` / `npm install vex-sdk`)
- **Core engine + dashboard** — AGPLv3 (self-host free, modifications to SaaS must be shared, commercial license available)

## License Mapping

| Component | License | Rationale |
|-----------|---------|-----------|
| `sdk/python/` | Apache 2.0 | Thin client, not the moat. |
| `sdk/typescript/` | Apache 2.0 | Same. |
| `services/` (all microservices) | AGPLv3 | Core engine. Copyleft protects SaaS value. |
| `nextjs-application/` (dashboard + landing) | AGPLv3 | Full-stack open source, GitLab/Grafana model. |
| Root `AgentGuard/` | AGPLv3 | Default for the monorepo. |

## Approach

Per-directory LICENSE files (Approach 1 from brainstorming). Standard for monorepos with split licensing (Grafana, Supabase pattern).

## Files to Create/Modify

1. **`LICENSE`** (root) — Full AGPLv3 text, copyright "2026 Vex AI, Inc."
2. **`LICENSING.md`** (root) — Human-readable dual-license explanation + commercial licensing offer
3. **`sdk/python/LICENSE`** — Update copyright from "Oppla.ai" to "Vex AI, Inc."
4. **`sdk/typescript/LICENSE`** — New Apache 2.0 file
5. **`services/LICENSE`** — New AGPLv3 file
6. **`nextjs-application/LICENSE`** — New AGPLv3 file

## Package Metadata Updates

- `sdk/python/pyproject.toml` — verify `license` field says `Apache-2.0`
- `sdk/typescript/package.json` — add `"license": "Apache-2.0"`

## LICENSING.md Content

- Which components are Apache 2.0 (SDKs) and why
- Which components are AGPLv3 (engine, dashboard) and what that means
- Commercial licensing: contact for proprietary license if AGPL doesn't work
- CLA note: contributions to AGPLv3 components grant Vex AI right to dual-license

## SPDX Headers

Add `SPDX-License-Identifier` to key entry-point files only (not every file).

## Business Model Alignment

- **SDKs (Apache 2.0):** Maximum adoption. Anyone can integrate without legal review.
- **Engine (AGPLv3):** Self-host free. If someone modifies and offers as SaaS, must share code. Vex AI (as copyright holder) can sell commercial licenses to enterprises avoiding AGPL.
- **Managed cloud (app.tryvex.dev):** The "easy button" — no self-hosting, no AGPL obligations. This is the primary revenue driver.
