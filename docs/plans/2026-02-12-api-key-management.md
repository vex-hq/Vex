# API Key Management — Design

**Date:** February 12, 2026
**Status:** Approved
**Scope:** Dashboard UI + backend validation + shared auth module

---

## 1. Overview

API key management enables design partners to generate, manage, and revoke keys that authenticate their SDK with AgentGuard backend services. Keys are stored as SHA-256 hashes in the existing `organizations.api_keys` JSONB column in TimescaleDB. Backend services validate keys via an in-memory cache with 60-second TTL.

### Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Storage | TimescaleDB `organizations.api_keys` JSONB | Column already exists. Backend services already connect to TimescaleDB. Keeps AgentGuard data in one DB. |
| Security model | Hash-only, show key once at creation | Industry standard (GitHub, Stripe, AWS). Prevents exposure via DB access. |
| Scopes | Operation-based: `ingest`, `verify`, `read` | Maps cleanly to service boundaries. Granular without over-engineering. |
| Metadata | Name, scopes, expiry, rate limits per key | Production-ready from day one. |
| Validation | In-memory cache, 60s TTL | No latency impact on hot path. Revocation delay acceptable (60s max). |

---

## 2. Key Format

```
ag_live_k7xR2mP9vN4qL8wT1jY6bC3dF5hG0sA
├──────┤├──────────────────────────────────┤
 prefix         32 random alphanumeric
```

- **Prefix:** `ag_live_` (8 chars) — identifiable in logs, env files, and secret scanners
- **Random part:** 32 alphanumeric characters (a-z, A-Z, 0-9)
- **Total length:** 40 characters
- **Display prefix:** first 12 chars (`ag_live_k7xR`) shown in dashboard for identification

---

## 3. Data Model

**JSONB structure in `organizations.api_keys`:**

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "prefix": "ag_live_k7xR",
    "key_hash": "a1b2c3d4e5f6...64-char-sha256-hex",
    "name": "Production",
    "scopes": ["ingest", "verify", "read"],
    "rate_limit_rpm": 1000,
    "expires_at": "2027-02-12T00:00:00Z",
    "created_at": "2026-02-12T14:30:00Z",
    "created_by": "supabase-user-uuid",
    "last_used_at": "2026-02-12T15:00:00Z",
    "revoked": false
  }
]
```

| Field | Type | Description |
|---|---|---|
| `id` | UUID | Unique identifier for this key |
| `prefix` | string | First 12 chars of the key, for dashboard display |
| `key_hash` | string | SHA-256 hex digest of the full key |
| `name` | string | Human-readable label (e.g., "Production") |
| `scopes` | string[] | Subset of `["ingest", "verify", "read"]` |
| `rate_limit_rpm` | integer | Max requests per minute (default: 1000) |
| `expires_at` | ISO 8601 / null | Expiry timestamp, null means no expiry |
| `created_at` | ISO 8601 | Creation timestamp |
| `created_by` | UUID | Supabase user ID who created the key |
| `last_used_at` | ISO 8601 / null | Last usage timestamp, updated in batches |
| `revoked` | boolean | Soft-delete flag, keeps audit trail |

**Constraints:**
- Maximum 10 keys per organization
- Key names must be non-empty, max 100 characters
- At least one scope required

---

## 4. Backend Validation Flow

```
Request arrives with X-AgentGuard-Key: ag_live_k7xR2m...
    │
    ▼
SHA-256 hash the incoming key
    │
    ▼
Check in-memory cache (dict keyed by hash)
    │
    ├── Cache HIT → check expiry, revoked, scopes → allow/deny
    │
    └── Cache MISS → query TimescaleDB
            │
            ▼
        SELECT org_id, api_keys FROM organizations
        WHERE api_keys @> '[{"key_hash": "<hash>"}]'
            │
            ├── No match → 401 Unauthorized
            │
            └── Match found → extract key entry from JSONB
                    │
                    ▼
                Validate: not revoked, not expired, has required scope
                    │
                    ├── Invalid → 401/403
                    │
                    └── Valid → cache result (60s TTL), return org_id
```

### Cached Entry

```python
{
    "org_id": "acme-corp",
    "key_id": "uuid",
    "scopes": ["ingest", "verify", "read"],
    "rate_limit_rpm": 1000,
    "expires_at": "2027-02-12T00:00:00Z",
    "cached_at": 1739370000.0
}
```

### Scope Enforcement

| Service | Required Scope |
|---|---|
| Ingestion API (`POST /v1/ingest`) | `ingest` |
| Sync Gateway (`POST /v1/verify`) | `verify` |
| Future read endpoints | `read` |

### Rate Limiting

Each cached entry tracks a sliding window counter (in-memory). When `rate_limit_rpm` is exceeded, the service returns `429 Too Many Requests` with a `retry_after_seconds` value. The counter resets when the cache entry expires.

### `last_used_at` Updates

Batched, not per-request. Each service accumulates key usage in memory and writes `last_used_at` to the database every 60 seconds asynchronously. This avoids write pressure on the hot path.

---

## 5. Dashboard UI

### Location

`/home/[account]/settings/api-keys` — new tab under team account settings.

### Page States

**Empty state:** Panel with key icon, "No API keys yet" message, "Create API Key" button, one-liner explaining purpose.

**Key list:** Table with columns:
- **Name** — human-readable label
- **Key** — masked prefix (`ag_live_k7xR••••`)
- **Scopes** — badges: `ingest` `verify` `read`
- **Rate Limit** — e.g., "1,000 rpm"
- **Expires** — date or "Never"
- **Last Used** — relative time or "Never"
- **Status** — green "Active" or red "Revoked"
- **Actions** — Revoke button with confirmation dialog

### Create Key Flow

1. User clicks "Create API Key"
2. Modal: name (required), scope checkboxes (all checked by default), rate limit input (default 1000), optional expiry date picker
3. Submit → server action generates key, hashes, stores in JSONB, returns full key
4. **Show-once modal:** full key in monospace box, copy button, yellow warning ("Copy this key now. You won't be able to see it again."), "Done" button

### Revoke Flow

Confirm dialog → sets `revoked: true` in JSONB → row shows "Revoked" badge, grayed out. Revoked keys remain visible for audit trail.

---

## 6. Implementation Components

### Dashboard (Next.js)

| File | Purpose |
|---|---|
| `apps/web/app/home/[account]/settings/api-keys/page.tsx` | Server component — fetches keys for org, renders page |
| `apps/web/app/home/[account]/settings/api-keys/_components/api-keys-table.tsx` | Client component — key list table with revoke actions |
| `apps/web/app/home/[account]/settings/api-keys/_components/create-key-dialog.tsx` | Client component — create form + show-once modal |
| `apps/web/lib/agentguard/api-keys.ts` | Server-only module — `createKey()`, `listKeys()`, `revokeKey()`, `updateLastUsed()` |
| `apps/web/app/home/[account]/settings/api-keys/_lib/api-keys-actions.ts` | Server actions — `createKeyAction`, `revokeKeyAction` wrapped with `enhanceAction()` |

### Backend (Python services)

| File | Purpose |
|---|---|
| `services/shared/shared/auth.py` | New shared module — `KeyValidator` class with cache, scope checking, rate limiting |
| `services/ingestion-api/app/auth.py` | Updated — uses `KeyValidator` with required scope `ingest` |
| `services/sync-gateway/app/auth.py` | Updated — uses `KeyValidator` with required scope `verify` |
| `services/migrations/alembic/versions/007_api_key_index.py` | GIN index on `organizations.api_keys` for JSONB containment queries |

### SDK

No changes needed. The SDK already sends `X-AgentGuard-Key` header — the key format is opaque to it.

---

## 7. Error Responses

| Scenario | Status | Body |
|---|---|---|
| Missing `X-AgentGuard-Key` header | 401 | `{"detail": "Missing X-AgentGuard-Key header"}` |
| Key not found | 401 | `{"detail": "Invalid API key"}` |
| Key revoked | 401 | `{"detail": "API key has been revoked"}` |
| Key expired | 401 | `{"detail": "API key has expired"}` |
| Key lacks required scope | 403 | `{"detail": "API key missing required scope: verify"}` |
| Rate limit exceeded | 429 | `{"detail": "Rate limit exceeded", "retry_after_seconds": 12}` |

> **Note:** In production, revoked/expired/not-found could be collapsed into a single "Invalid API key" response to prevent key enumeration attacks. The distinct messages above are useful during development and for design partner debugging.

---

## 8. Testing Strategy

### Backend — `services/shared/tests/test_auth.py`

Unit tests for `KeyValidator`:
- Valid key → returns org_id + scopes
- Invalid key → raises 401
- Revoked key → raises 401
- Expired key → raises 401
- Wrong scope → raises 403
- Rate limit exceeded → raises 429
- Cache hit (no DB query on second call)
- Cache expiry (DB query after TTL)
- Batched `last_used_at` writes

### Dashboard — server action tests

- `createKeyAction` returns full key once, stores only hash
- `listKeys` returns prefix, never full key
- `revokeKeyAction` sets `revoked: true`
- Max 10 keys per org enforcement
- Permission check — only owners/admins can manage keys

### Integration — end-to-end

- Generate key in dashboard → use key in SDK → verify request succeeds
- Revoke key → next request after cache TTL fails with 401

---

## 9. Migration

### `007_api_key_index.py`

```sql
CREATE INDEX ix_organizations_api_keys ON organizations
USING GIN (api_keys jsonb_path_ops);
```

Enables efficient JSONB containment queries (`@>`) for key hash lookups. No schema changes needed — the `api_keys` JSONB column already exists from migration 001.
