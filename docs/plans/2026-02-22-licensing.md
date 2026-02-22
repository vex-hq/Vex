# Vex Dual-License Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Apply Apache 2.0 to SDKs and AGPLv3 to core engine/dashboard with proper LICENSE files, metadata, and a LICENSING.md explainer.

**Architecture:** Per-directory LICENSE files at each component boundary. Root defaults to AGPLv3. SDKs carry Apache 2.0.

**Tech Stack:** License text files, pyproject.toml, package.json, SPDX headers.

---

### Task 1: Add root AGPLv3 LICENSE

**Files:**
- Create: `LICENSE`

**Step 1: Create the root LICENSE file**

Write the full GNU AGPLv3 license text to `LICENSE` at the repo root. Copyright line: `Copyright (C) 2026 Vex AI, Inc.`

Use the standard AGPLv3 text from https://www.gnu.org/licenses/agpl-3.0.txt

**Step 2: Commit**

```bash
git add LICENSE
git commit -m "chore: add AGPLv3 root LICENSE"
```

---

### Task 2: Add services/ AGPLv3 LICENSE

**Files:**
- Create: `services/LICENSE`

**Step 1: Create LICENSE**

Copy the same AGPLv3 text to `services/LICENSE`. Same copyright line.

**Step 2: Commit**

```bash
git add services/LICENSE
git commit -m "chore: add AGPLv3 LICENSE to services/"
```

---

### Task 3: Add nextjs-application/ AGPLv3 LICENSE

**Files:**
- Create: `nextjs-application/LICENSE`

**Step 1: Create LICENSE in the submodule**

```bash
cd nextjs-application
```

Write AGPLv3 text to `nextjs-application/LICENSE`. Same copyright.

**Step 2: Commit in submodule**

```bash
cd nextjs-application
git add LICENSE
git commit -m "chore: add AGPLv3 LICENSE to dashboard"
```

---

### Task 4: Update Python SDK license and metadata

**Files:**
- Modify: `sdk/python/LICENSE` — update copyright from "Oppla.ai" to "Vex AI, Inc."
- Modify: `sdk/python/pyproject.toml:12-13` — update authors from "Oppla.ai" to "Vex AI, Inc."

**Step 1: Update copyright in LICENSE**

Change line 179:
```
Copyright 2026 Oppla.ai
```
to:
```
Copyright 2026 Vex AI, Inc.
```

**Step 2: Update authors in pyproject.toml**

Change:
```toml
authors = [
    {name = "Oppla.ai", email = "eng@oppla.ai"},
]
```
to:
```toml
authors = [
    {name = "Vex AI, Inc.", email = "eng@tryvex.dev"},
]
```

**Step 3: Commit**

```bash
git add sdk/python/LICENSE sdk/python/pyproject.toml
git commit -m "chore: update Python SDK copyright to Vex AI"
```

---

### Task 5: Add TypeScript SDK LICENSE and update metadata

**Files:**
- Create: `sdk/typescript/LICENSE` — Apache 2.0 text, copyright "2026 Vex AI, Inc."
- Modify: `sdk/typescript/package.json:28` — update author from "Oppla.ai" to "Vex AI, Inc."

**Step 1: Create LICENSE**

Write the full Apache 2.0 license text (same as `sdk/python/LICENSE`) to `sdk/typescript/LICENSE`. Copyright: `Copyright 2026 Vex AI, Inc.`

**Step 2: Update package.json author**

Change:
```json
"author": "Oppla.ai <eng@oppla.ai>",
```
to:
```json
"author": "Vex AI, Inc. <eng@tryvex.dev>",
```

**Step 3: Commit**

```bash
git add sdk/typescript/LICENSE sdk/typescript/package.json
git commit -m "chore: add Apache 2.0 LICENSE to TypeScript SDK, update copyright"
```

---

### Task 6: Create LICENSING.md

**Files:**
- Create: `LICENSING.md`

**Step 1: Write LICENSING.md**

```markdown
# Licensing

Vex uses a dual-license model.

## SDKs — Apache 2.0

The client SDKs are licensed under the Apache License 2.0:

- `sdk/python/` — [PyPI: vex-sdk](https://pypi.org/project/vex-sdk/)
- `sdk/typescript/` — [npm: @vex_dev/sdk](https://www.npmjs.com/package/@vex_dev/sdk)

You can use, modify, and distribute the SDKs freely in any project, commercial or otherwise, with no copyleft obligations.

## Core Engine & Dashboard — AGPLv3

Everything else — the verification engine, ingestion API, alert service, dashboard, and all supporting services — is licensed under the GNU Affero General Public License v3.0:

- `services/` — All backend microservices
- `nextjs-application/` — Dashboard and landing page

You can self-host the entire Vex stack for free. If you modify the AGPLv3 components and offer them as a network service, you must make your modifications available under AGPLv3.

## Commercial License

If the AGPL doesn't work for your organization, we offer commercial licenses that remove the copyleft requirement. Contact **sales@tryvex.dev** for details.

## Managed Cloud

The easiest way to use Vex is our managed cloud at [app.tryvex.dev](https://app.tryvex.dev). No self-hosting, no license obligations — just `pip install vex-sdk` and point at our API.

## Contributing

By submitting a pull request, you agree that your contributions to AGPLv3-licensed components may be dual-licensed by Vex AI, Inc. under both AGPLv3 and a commercial license. SDK contributions remain under Apache 2.0.
```

**Step 2: Commit**

```bash
git add LICENSING.md
git commit -m "docs: add LICENSING.md explaining dual-license structure"
```

---

### Task 7: Update parent repo submodule and push

**Step 1: Push submodule (if Task 3 created a commit there)**

```bash
cd nextjs-application && git push && cd ..
```

**Step 2: Update submodule reference**

```bash
git add nextjs-application
git commit -m "chore: update nextjs-application submodule (AGPLv3 LICENSE)"
```

**Step 3: Push everything**

```bash
git push
```
