# BizAssist — Subscription, Activation Codes, Multi-Device & Robustness Plan

*Author: engineering session, 2026-07-06. Scope: the paid tier (Pro), activation-code
licensing, multi-device handling, admin-console hardening, and the prioritized route to
production robustness. Aligns with `docs/BIZASSIST_ECOSYSTEM_MASTER_PLAN.md`,
`docs/ADMIN_CONSOLE_PLAN.md`, and `docs/HOSTING_MODE_MASTER_PLAN.md`.*

---

## 0. What already shipped in this session (baseline)

These are done and tested; the plan below builds on them.

- **Sync correctness** — `register_shifts` / `shift_cash_movements` enqueue + apply (parent-FK
  resolution), chunked push with a realistic timeout, in-flight guard, idle-skip, quiet logs.
- **Plan gating** — `/api/sync/push`, `/api/sync/pull`, `/ask`, `/ask/stream` are gated by
  `require_plan("pro")`. **Dormant** until `SUBSCRIPTION_ENFORCED=1` (per backend).
- **Single source of premium** — `/profile.is_premium` = *active paid plan* **OR** the legacy
  `is_premium` column. Subscription lives in `users.settings.subscription` (admin-only; stripped
  from client `PUT /settings`).
- **402 handling** — cloud refuses free-plan sync; the desktop worker **pauses** (no retry storm)
  and surfaces "Cloud sync requires the Pro plan"; the web mode-switch aborts with an upgrade
  message instead of falsely reporting success. Resumes on next login after upgrade.
- **Segregation logging** — `[PLAN] tier=… decision=…` on every gated request (block=INFO,
  allow=DEBUG) + a `[PLAN] login tier=…` line once per session.
- **AI key** — `/ask*` uses the shared `GROQ_API_KEY` from `.env`; free users are refused, Pro
  users share the key. (No per-user keys needed.)

Tests: `tests/test_plan_gating.py`, `tests/test_sync_shift_and_push_hardening.py`,
updated `tests/test_auth_logging.py`, `tests/test_profile_is_premium.py`.

---

## 1. Activation-code subscription (the requested model)

**Goal:** admin generates a per-business code that encodes plan + duration (+ features + device
cap). The owner pastes it into their Profile → it activates → Profile shows "N days left". The
owner **cannot edit it once applied**; only an admin can change/extend/revoke. This is the offline-
friendly licensing flow retail owners recognize.

This reuses the existing, proven **connection-code** pattern (seller-issued, single-use,
expiring — see `core/api/connections.py`, `connection_codes`) and the existing
`users.settings.subscription` store.

### 1.1 Data model — `activation_codes` (new table, cloud-authoritative)

| Column | Type | Notes |
|---|---|---|
| `id` / `uid` | int / uuid | standard |
| `code` | string, unique, indexed | the human-typed token (see 1.3) |
| `plan` | string | `pro` (extensible: `pro_plus`, …) |
| `duration_days` | int | e.g. 365; drives `expires_at` at redeem time |
| `features` | JSON | optional per-code overrides (`{"ai": true, "max_devices": 3}`) |
| `max_devices` | int | device cap granted by this code |
| `issued_for_bizid` | string, nullable | bind to one business (recommended) or leave open |
| `issued_by` | string | admin username (audit) |
| `issued_at` | datetime | |
| `code_expires_at` | datetime, nullable | *code* validity (must be redeemed before this) |
| `status` | string | `issued` → `redeemed` → (`revoked`) |
| `redeemed_by_business_id` | int, nullable | who activated it |
| `redeemed_at` | datetime, nullable | |

Keep this table **cloud-only** (like `connection_codes`); never sync it to devices.

### 1.2 Flows

**Admin issues (Admin Console):**
`POST /admin/activation-codes` → `{plan, duration_days, features, max_devices, issued_for_bizid?,
code_expires_at?}` → returns the generated `code`. Audit-logged (existing `audit_log`). List/revoke:
`GET /admin/activation-codes`, `POST /admin/activation-codes/{id}/revoke`.

**Owner redeems (Profile → "Activate subscription"):**
`POST /subscription/redeem { code }` (owner-only, `restrict_cashier`, rate-limited):
1. Look up `code`; reject if not `issued`, expired (`code_expires_at`), or `issued_for_bizid`
   mismatches the caller's BizID.
2. Compute `expires_at = now + duration_days`.
3. Write `users.settings.subscription = {plan, status:"active", expires_at, activated_via:code,
   granted_by:"self-redeem", granted_at:now}` — **exactly the shape `effective_plan()` already
   reads**, so all gates work with zero new plumbing.
4. Mark the code `redeemed` (single-use).
5. Return the subscription view (plan + days remaining).

**Non-editable by owner:** `PUT /settings` already strips + preserves the `subscription` key, so the
owner physically cannot change it. Admin edits go through `POST /admin/subscription/{business_id}`
(exists) — no change needed.

**Days remaining:** extend `_subscription_view()` to also return
`days_remaining = ceil((expires_at - now).days)` and `expires_at`. `effective_plan()` already
downgrades to `free` past expiry, so an expired sub self-disables — the Profile just needs to render
the number.

### 1.3 Code format (secure + offline-verifiable)

Two options; recommend **B** for retail:

- **A. Opaque random token** (like connection codes): 12–16 char base32, stored server-side. Simple,
  requires a cloud lookup to redeem (fine — redeem is online).
- **B. Signed/self-describing token (recommended):** `BZ-<plan>-<days>-<rand>-<hmacsig>`, where
  `hmacsig = HMAC_SHA256(secret, plan|days|rand)[:8]`. The server verifies the signature so the code
  is tamper-evident even before the DB row is consulted, and the plan/duration are legible for
  support. Still recorded server-side for single-use enforcement. Secret in env (`ACTIVATION_HMAC_SECRET`).

Never encode secrets in the code; the HMAC only proves *we* minted it.

### 1.4 Effort: ~1 focused day. New: 1 table + 1 migration, 2 admin routes, 1 owner route, a Profile
card, `days_remaining` on the subscription view, `tests/test_activation_codes.py`
(issue→redeem→expiry→single-use→wrong-biz→revoke).

---

## 2. Multi-device (same owner, many devices)

**Today:** each device runs its own local SQLite + hybrid-syncs to **one** cloud business keyed by
**BizID** (`public_id`), which is the stable cross-DB identity. LWW convergence already handles two
devices editing the same rows. `telemetry` already carries a `device_id`. So multi-device *data* works;
what's missing is **device identity, a cap, and visibility**.

### 2.1 Design

- **Subscription binds to the business (BizID), not the device.** All devices under one BizID share
  the one `settings.subscription` on the cloud → every device is Pro once the business is Pro. The
  activation code is redeemed once, per business.
- **New `devices` table (cloud):** `(business_id, device_id, name, platform, first_seen, last_seen,
  status)`. The desktop already generates a stable `device_id` (telemetry) — reuse it.
- **Register on login/sync:** the sync worker (or a `POST /devices/heartbeat`) upserts
  `(business_id, device_id, last_seen)`. Cheap, gives the admin a live device list.
- **Enforce `max_devices`** (from the plan/code) at the cloud boundary: when a *new* `device_id`
  appears and the business already has `max_devices` **active** devices, return `409/402`
  "Device limit reached — deactivate a device or upgrade." The desktop surfaces this like the 402
  pause. Existing devices are unaffected (LWW keeps them converged).
- **Admin visibility/control:** `GET /admin/businesses/{id}/devices`, deactivate a device
  (`POST …/devices/{device_id}/deactivate`) so a lost/replaced machine frees a seat.

### 2.2 Conflicts: already handled. LWW + durable `uid` keys mean two devices editing the same product
converge (cloud-wins on tie). The one thing to watch: **invoice-number collisions** across devices —
the codebase already addresses this with per-login `counter_prefix` (C1-0001 vs C2-0001), so two
devices never mint the same invoice id. Keep that requirement for multi-device Pro.

### 2.3 Effort: ~1 day. 1 table + migration, heartbeat/registration in the worker, a cap check on the
sync/token path, 2 admin routes, `tests/test_devices.py` (register→cap→deactivate→reuse).

---

## 3. Admin console — clean & robust (so "this should not break")

The admin surface exists (`frontend-admin/`, `routes/admin.py`, `services/admin_service.py`) with
fail-closed `ADMIN_API_ENABLED`, `require_admin`, audit logging, and type-to-confirm wipes. Harden it
around the new subscription/device features:

1. **One premium source (done):** `is_premium` now derives from `effective_plan` OR the column — the
   admin grant, the activation redeem, and a manual column flip all agree. No more split-brain.
2. **Subscription tab additions:** show `plan · status · days_remaining · device_count` per business
   (extend `list_businesses`, which already returns `hosting_mode`, `plan`, sync stats). Actions:
   grant/extend/revoke, issue activation code, list/deactivate devices.
3. **Robustness rules to bake in:**
   - All subscription/device writes go through the service layer with `require_admin` + `audit_log`
     (pattern exists) — never let the client set `subscription`/`is_premium` directly.
   - Validate plan against `VALID_PLANS`; reject unknown plans (exists) — extend when adding tiers.
   - Tolerate malformed `users.settings` JSON everywhere (use `_settings_dict`'s try/except — exists).
   - Idempotent grants (granting the same plan twice is a no-op update, not a duplicate).
   - Rate-limit `/subscription/redeem` (reuse `services/rate_limiter.py`) to stop code-guessing.
   - Keep `frontend-admin` out of the desktop installer and off customer Vercel URLs (already a
     stated rule in `ADMIN_CONSOLE_PLAN.md`).
4. **Tests:** `test_admin_console_sso.py` exists (14 cases). Add subscription + activation + device
   admin cases to keep the surface green as it grows.

---

## 4. Prioritized route to robustness (the "best route")

Ordered by risk-reduction per unit effort. Items marked ✅ shipped this session.

**Phase 0 — land what's done (this week)**
- ✅ Sync + plan-gate + logging changes. **Redeploy backend→HF, frontend→Vercel.**
- Set `JWT_SECRET` (≥32 bytes, identical local+cloud). Set `SUBSCRIPTION_ENFORCED=1` **on cloud only**
  when ready to charge (leaves local billing free).
- Run the full suite; confirm the two previously-failing tests are green.

**Phase 1 — monetization correctness (1–2 days)**
- Activation codes (§1) + `days_remaining` in Profile.
- Turn on enforcement on cloud; grant Pro to pilot businesses (incl. Varshini_Dev) so they aren't cut
  off. Verify the 402 pause + upgrade toast on a real free account.

**Phase 2 — multi-device (1–2 days)**
- `devices` table + registration + `max_devices` cap + admin device list (§2).

**Phase 3 — platform hardening (from `ARCHITECTURE_REVIEW_AND_PLAN.md`, still open)**
These are the pre-existing scale risks the review flagged; they matter once you have paying,
multi-device, multi-worker traffic:
- **C5 — process-local state** (`context_cache`, rate-limit windows, APScheduler) breaks with
  `--workers >1` / HF autoscaling → **pin to one worker and document it, or move shared state to
  Redis.** Pick one before scaling out. (The sync scheduler must run on exactly one instance —
  relevant to multi-device too.)
- **C3 — token accounting undercounts** (`_polish`, CONVERSATIONAL, non-stream AI report 0 tokens) →
  budgets/billing are fiction until fixed. Important once AI is the paid layer.
- **H1 — errors returned as 200 bodies** → standardize an error envelope + real HTTP codes.
- **C4 — global cache invalidation on upload** → use `invalidate_user_cache(user_id)` (already exists).

**Phase 4 — trust & polish**
- Full reconcile ("Sync everything") button reusing the migrate engine (recommended earlier) for
  stuck-outbox self-heal and initial seeding.
- Device/session audit surfaced to the owner (not just admin) for the "unbreakable/secure" USP.

---

## 5. USP alignment check

The master plan's four goals — **easy to use · secure & unbreakable · addictive · makes money** —
map to this work as follows:

| USP | This plan's contribution | Aligned? |
|---|---|---|
| **Easy to use** | Activation code = paste-one-string upgrade owners recognize; days-remaining is legible; 402s explain instead of erroring. | ✅ |
| **Secure & unbreakable** | Cloud-authoritative subscription/codes/devices; admin-only, audited; single-use signed codes; device cap; sync self-heals; fail-closed admin API. | ✅ |
| **Addictive** | Multi-device "my shop everywhere," AI advisor as the paid hook, network effects (connection codes pull retailers into the paid orbit — master plan §"network multiplies seats"). | ✅ (depends on Phase 1–2) |
| **Makes money** | Enforcement at the cloud boundary can't be bypassed by a local desktop; per-business codes with duration = clean renewals; device cap protects seat economics; AI gated to Pro. | ✅ |

**One misalignment to decide (product call):** the master plan says *"the customer ordering network
requires the cloud"* and *"AI is the paid intelligence layer."* Today a **free** account can enable
Local+Cloud on the desktop and sync (because the local backend doesn't enforce and, until now, the
cloud accepted pushes). With `require_plan` on the sync endpoints + `SUBSCRIPTION_ENFORCED=1` on
cloud, that bypass closes — **which is the intended monetization**, but it means cloud sync becomes a
paid feature. Confirm that's the intent (it matches the master plan). Local-only billing stays free
and fully functional, preserving "billing first, free front door."

---

## 6. One-glance next actions

1. Redeploy (backend→HF, frontend→Vercel); set `JWT_SECRET`; run suite green.
2. Decide: cloud sync = Pro-only? (Recommended yes — matches master plan.) If yes, set
   `SUBSCRIPTION_ENFORCED=1` on cloud and grant pilots Pro.
3. Build activation codes (§1) → owners self-activate; admin issues/extends/revokes.
4. Build device registry + cap (§2).
5. Schedule Phase 3 platform-hardening (C5 worker/state first) before scaling to many paying devices.
