# Admin Console & SSO Integration Plan

> **Status (2026-07-04): Phases A, B, C implemented.**
> C — SSO handoff/redeem live (billing → Dashboard, single-use 30s tickets).
> A — `frontend-admin/` extracted; `ADMIN_API_ENABLED` gate is fail-closed
>   (default **0** → `/admin/*` returns 404; HF Dockerfile sets 1); audit log on
>   every admin mutation (`logs/admin_audit.jsonl`); type-the-name wipe confirm.
> B — fleet fields on `/admin/businesses`; `/admin/telemetry(+/devices)`,
>   `/admin/server-log`, `/admin/audit-log`; Telemetry & Logs tab; subscriptions
>   in `users.settings.subscription` (admin-only, preserved+stripped on client
>   PUT /settings) with `require_plan("pro")` hooks on `/ask*` + hybrid
>   activation — dormant until `SUBSCRIPTION_ENFORCED=1`.
> Tests: `backend/tests/test_admin_console_sso.py` (14 cases) + suite green.

**Goal:** one clean, organiser-only Admin Console (monitor · debug · logs · limits · subscriptions), completely invisible to customers — plus seamless owner access from the billing app into Dashboard BIZASSIST (no second login).

**What already exists (audit, 2026-07-04):**

| Piece | Where | State |
|---|---|---|
| Admin UI (Dashboard, Businesses, Cache, Usage, Login) | `frontend-ai/src/pages/admin/*`, `AdminLayout` | working, styled |
| Server-side guard | `svc.require_admin()` on every `/admin/*` route | working |
| `admin` role + separate admin login flow | `routes/auth.py`, frontend-ai `adminLogin()` | working |
| Rate limits per business | `RateLimitConfig` + `/admin/rate-limits/{id}` GET/POST | working, has UI |
| Telemetry sink (desktop → local + cloud) | `routes/telemetry.py`, `logs/telemetry.jsonl` | working, **no viewer yet** |
| One-time ticket infra (30 s TTL, single-use) | `create_sse_ticket` in `services/auth.py` | working (SSE only) |
| Subscription concept | `AI_DASHBOARD_GATED` flag (frontend), PRO badge styling | placeholder only |

So this is mostly **extraction + wiring**, not greenfield.

---

## Phase A — Extract the Admin Console into its own app (organiser-only)

**Why separate:** it must never ship inside the desktop installer, never be reachable on a customer's Vercel URL, and evolve independently.

1. **New folder `frontend-admin/`** (Vite + React, same stack). Move `frontend-ai/src/pages/admin/*` + `AdminLayout` + `ProtectedRoute` (admin branch) + admin CSS into it. frontend-ai keeps only the owner-facing dashboard (its sidebar/router loses all `/admin/*` routes).
2. **Deploy cloud-only**: private Vercel project (e.g. `admin-bizassist.vercel.app`), pointed at the HF cloud backend only. Optionally protect with Vercel password/allowed-IP on top of app login (defence in depth).
3. **Harden the backend edge:**
   - `ADMIN_API_ENABLED` env (default `0`). The desktop/PyInstaller build never sets it → `/admin/*` returns 404 on every customer machine. HF Space sets `1`.
   - Keep `svc.require_admin` as the second layer.
   - Add an audit log: every `/admin/*` mutation writes who/what/when (reuse telemetry JSONL pattern; no migration).
4. **Do NOT add admin routes/UI to frontend-billing.** What billing owners get instead is a read-only "My plan & usage" card in Settings (their own limits/subscription — Phase C).

**Effort:** ~½ day. No schema changes.

---

## Phase B — Console features: monitor · debug · logs · limits · subscriptions

New tabs in `frontend-admin`, new endpoints in `routes/admin.py` (all behind `require_admin`):

1. **Fleet monitor** (extend `/admin/businesses`): per business — hosting mode, last sync time + queue depth (`SyncLog`/`SyncQueue`), app version & platform (join latest telemetry by device), online-in-last-24h.
2. **Telemetry / logs viewer**: `GET /admin/telemetry?device=&event=&level=&since=&limit=` reading `logs/telemetry.jsonl` (newest-first, filterable). UI: live table + level badges + expandable payloads (`backend_start_failed` log tails render in a `<pre>`). Later (post-testing): move ingestion to a `telemetry_events` table — **that's the one alembic migration in this plan** (deferred until JSONL hurts).
3. **Debug tools**: surface existing endpoints — cache stats/flush, router-mode, business-details — plus new `GET /admin/server-log?lines=200` (tail of `bizassist.log`).
4. **Limits**: UI already exists (`AdminUsage`/rate-limits) — port as-is, add bulk edit.
5. **Subscriptions** (new, but schema-free):
   - Store in the existing `users.settings` JSON: `settings.subscription = { plan: "free"|"pro", status, expires_at, granted_by, note }` → no migration, syncs with existing settings machinery.
   - `GET/POST /admin/subscription/{business_id}` (grant/extend/revoke) + grid in the console with expiry countdowns.
   - **Enforcement hooks** (read-side): `/settings` already returns merged settings → frontend-billing flips `AI_DASHBOARD_GATED` from the user's real plan instead of the hardcoded const; backend guards AI routes (`/ask*`) and hybrid sync activation with a `require_plan("pro")` dependency. Free = local billing forever; Pro = AI + hybrid sync (matches the onboarding modal's pitch).

**Effort:** ~1–1.5 days. Zero migrations now; one deferred.

---

## Phase C — SSO: billing → Dashboard BIZASSIST (owner, no re-login)

**Problem:** frontend-ai (port 8451/5173) is a different origin than billing (8450/5174) — localStorage isn't shared, so the new window asks for login again.

**Solution — reuse the proven ticket pattern** (already used for SSE auth):

1. Backend: generalise `create_sse_ticket` → `POST /auth/handoff-ticket` (requires an authenticated **owner**; staff/cashier 403). Returns `{ticket}` — single-use, 30 s TTL, carries the user payload.
2. Billing (`aiDashboard.js`): `openAiDashboard()` becomes: fetch handoff ticket → `window.open(AI_URL + '/?sso=' + ticket)`. Falls back to plain open if the call fails.
3. frontend-ai boot (`AuthContext`): if `?sso=` present → `POST /auth/redeem-ticket` → full JWT session → save, strip the param from the URL, render dashboard. No ticket/invalid → normal login page (unchanged fallback).
4. Owner-only stays enforced twice: ticket minting refuses non-owners, and frontend-ai's `ProtectedRoute` keeps its role check.
5. Desktop shell: no change needed — `openAiWindow(url)` already passes through the full URL.

**Effort:** ~½ day. Also fixes web deployments (same mechanism works on any origin pair).

---

## Rollout order & risks

1. **C first** (SSO) — smallest, immediately visible UX win, no security surface change.
2. **A** (extraction + `ADMIN_API_ENABLED` hardening) — do before any real users install anything.
3. **B** incrementally — telemetry viewer first (you need it for field testing *now*), subscriptions last (needs product decisions: pricing, what's gated).

| Risk | Mitigation |
|---|---|
| Admin endpoints currently live on every desktop install | Phase A env-gate — ship in the next tag even if the console isn't built yet |
| `wipe-all-data` / `wipe-user-data` are one 403 away from disaster | keep behind `require_admin` + add type-the-business-name confirmation in console UI + audit log |
| Subscription in settings JSON = user-editable via PUT /settings? | server must strip `subscription` from client-supplied settings patches (one-line guard in the settings merge) |
| Ticket in URL could leak via logs | 30 s TTL + single-use + only ever on localhost origins in the desktop app |
