# Audit — Logging / Error-handling / Tests / `[BizId]`

Two parts:

- **Part A — Repo-wide audit** (§A1–A5): the whole codebase (backend + all three
  frontends + desktop), by area: logging levels, try/except coverage, test
  coverage, and `[BizId]` presence.
- **Part B — Changed-file audit** (§B1–B5): line-by-line detail of the files
  touched in the two work rounds (hosting/auth/feedback), with recommended tests.

Legend: ✅ present · ⚠️ partial · ❌ missing · n/a not applicable
Counts gathered by static grep (excludes `node_modules`, `venv`, `__pycache__`,
`dist`, `.git`). Treat as indicative, not exact.

---

## ✅ Implementation status (updated)

The recommendations below have now been **implemented** (this is no longer just
an audit):

- **`[BizId]` logging — DONE, backend + all three frontends.**
  - Backend: `current_bizid_var` ContextVar + `_BizIdFilter` inject `[BizId=…]`
    into every line; set once per request in `get_active_user`. Opt-in
    structured JSON via `LOG_FORMAT=json` (ECS-aligned, `biz_id` first-class).
  - Frontend-billing: `logger` now tags `[BizId=…]`, the 💎 prefix removed, and
    **warn/error are forwarded to the telemetry sink** (→ backend + cloud, and
    the backend log file when `LOG_FILE` is set). Fixed a real bug: telemetry
    read the wrong key (`user` vs `billing_user`) so the BizID never attached;
    `public_id` is now stored in the session and set on login/restore/logout.
  - frontend-admin / frontend-ai: **new** `logger` utils (previously none), with
    `[BizId=…]` and a BizID-sync effect in each AuthContext (AI also forwards to
    its telemetry sink).
- **`console.*` sweep — DONE.** All app `console.*` routed through the logger.
  Only 3 remain by design: `config.js` (would cycle with the logger's import of
  telemetry→config), `config/aiDashboard.js` (bootstrap), and one commented-out
  line in `CheckoutModal.jsx`.
- **Theme** now defaults to `system` (follows OS) with a one-time toast.
- **Tests T1–T9** added (see §B3) — runnable via `pytest` / `vitest`.

Known issue newly documented (see §B6): **username uniqueness vs. business
deletion** — deleting a business's data doesn't free its (globally unique)
username, so re-registration hits "Username already exists". Fix options in §B6.

---

# PART A — Repo-wide audit

## A1. Inventory & totals

| Area | Source files | Test files | Logger calls (i/w/e) | Raw `console.*` | `try` blocks |
|------|-------------:|-----------:|:--------------------:|----------------:|-------------:|
| `backend` (Python, excl tests/alembic) | 141 | **83** | 274 / 128 / 181 (+2 critical, 0 `exception`) | n/a | 738 |
| `frontend-billing` | 96 | 25 (+2 e2e) | 87 / 33 / 58 | 19 ⚠️ | 157 |
| `frontend-admin` | 33 | **1** ❌ | **0** (uses `console`) | 22 ❌ | 39 |
| `frontend-ai` | 37 | **1** ❌ | **0** (uses `console`) | 15 ❌ | 48 |
| `desktop/src` (Electron) | 6 | 0 | via telemetry | 0 | 9 |

## A2. `[BizId]` presence — the headline gap

| Signal | Count (repo-wide) |
|--------|------------------:|
| Literal `[BizId` tag in any log | **0** |
| Backend log lines referencing `public_id` (the BizID) | 4 |
| Backend log lines referencing "business" (mostly numeric `business_id`) | 77 |
| Frontend log lines referencing a BizID | 5 |

**Conclusion:** there is **no standardized business identifier on any log line**
today. A handful of lines print `public_id`/`business_id` ad-hoc. To grep one
business's trail across tiers (and to map to an Elasticsearch keyword field for
DDP metrics), a uniform `[BizId=BA-XXXXXX]` field is needed — design in §A5 / §B4.

## A3. Logging consistency

- **Backend** — good baseline: single `logging_config.py`, a `TAG` class of
  greppable tags (`[AUTH]`, `[ADMIN]`, `[SCHED]`, …), third-party loggers pinned
  to WARNING, a `current_username_var` ContextVar already in place. Level mix is
  healthy (info-heavy, errors present). Gap: no `[BizId]`; `logger.exception`
  is used 0× (stack traces ride on `error(..., exc_info=True)` instead).
- **frontend-billing** — has a real `logger` util (`💎 [BizAssist:Billing]`
  prefix, level colours), used ~178× — but **19 stray `console.*`** bypass it
  (inconsistent, and `console.log` ships to prod).
- **frontend-admin / frontend-ai** — ❌ **no logger util at all**; 37 raw
  `console.*` calls. No prefix, no level discipline, not prod-gated.
- **desktop** — clean (routes through telemetry).

## A4. Error-handling & test coverage — hotspots

| Finding | Where | Note |
|---|---|---|
| **131 broad/bare `except`** (`except:` / `except Exception`) | backend | Swallows errors; several pair with only a `pass`. Audit for silent failures (this is the class of bug behind the original "cloud switch fails silently"). |
| Areas with **error logs but ~no `try`** | `backend/core/billing` (0 error / 5 try), `core/accounting` (0 try), `core/agent` (0 log / 0 try) | Confirm exceptions are handled by a caller/decorator, else unguarded. |
| **Under-tested frontends** | `frontend-admin` (33 src / 1 test), `frontend-ai` (37 src / 1 test) | Highest test-debt in the repo. |
| Strong coverage | `backend` (141 src / 83 tests), `frontend-billing` (96 / 27) | Keep the ratio when adding features. |
| Stray `console.*` in prod bundle | `frontend-billing` (19), admin (22), ai (15) | Route through a logger; strip `console.log` in build. |

## A5. Repo-wide recommendations (priority order)

1. **Adopt `[BizId=…]` everywhere** (design in §B4). Backend: one `ContextVar` +
   a `logging.Filter` in `logging_config.py` → every line tagged, zero per-call
   edits. Frontend: `logger.setBizId()` on login, prefix in `logger.*`.
2. **Give `frontend-admin` and `frontend-ai` a shared `logger` util** (copy
   `frontend-billing/src/utils/logger.js`) and replace the 37 `console.*` calls.
3. **Sweep the 131 broad `except`** for silent swallows — at minimum log at
   WARNING with context before `pass`.
4. **Raise admin/AI frontend test coverage** toward the billing ratio.
5. **Strip `console.log`** in production builds; forbid via lint rule
   (`no-console` allowing only `warn`/`error`).
6. Prepare for Elasticsearch: emit backend logs as structured JSON (ECS-style
   `biz_id`, `component`, `tag`, `level`) behind a `LOG_FORMAT=json` env flag, so
   the same `[BizId]` field becomes a first-class searchable/aggregatable field
   for DDP metrics.

---

# PART B — Changed-file audit (hosting / auth / feedback)

Scope: every file touched across the two work rounds. For each file this records
**what changed**, its **info/warn/error logging**, its **try/except (try/catch)
coverage**, and its **test coverage / gap**.

---

## 1. Work performed (change log)

| # | File | Change |
|---|------|--------|
| 1 | `frontend-billing/src/pages/Support.jsx` | Feedback submit: pass PATH to `authFetch` (it already prepends `API_BASE`) — fixes the doubled `…8001http://…8001/feedback/submit` URL. Removed now-unused `API_BASE` import. |
| 2 | `frontend-billing/src/layouts/AppLayout.jsx` | Removed `HostingOnboardingModal` (the intrusive post-login pop-up); mounted `WebLocalOnlyNotice`. |
| 3 | `frontend-billing/src/pages/Login.jsx` | `handleOwnerContinue`: `/staff-counters` now falls back to cloud when the local mirror has no staff (fixes missing Owner/Staff picker on a fresh Windows device). |
| 4 | `frontend-billing/src/contexts/AuthContext.jsx` | `signup` auto-configures hosting (local / hybrid) — no migrate/relogin; new `setHostingMode` (no-logout Local↔Local+Cloud); `staffLogin` cloud fallback for a fresh device; exposed `setHostingMode`. |
| 5 | `frontend-billing/src/pages/Register.jsx` | Two options only (Local / Local + Cloud); passes `hosting` to `signup`; always navigates to `/` (no settings-switch deep-link). |
| 6 | `frontend-billing/src/pages/Settings.jsx` | Dropped pure-Cloud card; relabelled hybrid → "Local + Cloud"; `cardState`/`handleCardClick` two-mode; Local switch is instant/no-logout; legacy `cloud` maps to `hybrid`; removed unused `CloudIcon` import. |
| 7 | `frontend-billing/src/utils/loginSync.js` | Divergence sense is now **premium-gated** and **bidirectional** (cloud→local and local→cloud); reads `is_premium` from `/profile`. |
| 8 | `frontend-billing/src/components/hosting/SyncNudgeModal.jsx` | Handles both sync directions (title/body/button + `BackupModal` direction). |
| 9 | `frontend-billing/src/components/hosting/WebLocalOnlyNotice.jsx` | **New** — web-only notice for a Local-only account (data is on the desktop; log in there or upgrade). |
| 10 | `frontend-billing/src/components/hosting/MigrationModal.jsx` | Net no change (a temporary edit was reverted to keep the `onError`-on-failure test green). |
| 11 | `backend/database/models.py` | `User.is_premium` boolean column (default false). |
| 12 | `backend/database/migration.py` | Runtime migrator entry adding `users.is_premium`. |
| 13 | `backend/alembic/versions/ba1f7c3e9d20_add_user_is_premium.py` | **New** Alembic migration (parity with the runtime migrator). |
| 14 | `backend/routes/auth.py` | `/profile` GET + PUT now return `is_premium`. |
| 15 | `backend/services/admin_service.py` | `read_audit_log`: quiet WARNING + file fallback (was ERROR+traceback spam on every poll); per-row `detail` parse guarded. |

---

## 2. Per-file audit — logging / try-catch / tests

### Frontend

| File / unit | info | warn | error | try/catch | BizId in logs | Tests |
|---|---|---|---|---|---|---|
| `Support.jsx` `handleSubmit` | ❌ | ❌ | ✅ `console.error('Feedback submit error', err)` | ✅ around fetch | ❌ | ❌ no test for `/feedback/submit` (see gap T1) |
| `AppLayout.jsx` | n/a | n/a | n/a | ✅ (existing toast handler) | ❌ | ⚠️ layout not unit-tested |
| `Login.jsx` `handleOwnerContinue` | ❌ | ❌ | ❌ (silent `catch {}` on lookups) | ✅ local + cloud lookups each guarded | ❌ | ❌ (see gap T2) |
| `AuthContext.signup` | ✅ attempt + `[SIGNUP] BizID {bizId} mirrored` | ✅ hosting auto-setup skipped | ❌ | ✅ hosting block + `_doSignup` throws surfaced | ✅ **BizID logged** on mirror line | ❌ (see gap T3) |
| `AuthContext.setHostingMode` | ✅ set + done | ✅ save failed | ❌ | ✅ around PUT | ❌ | ❌ (see gap T3) |
| `AuthContext.staffLogin` | ✅ attempt + success + fresh-device | ✅ cloud fallback failed | ✅ staff login failed | ✅ around cloud fallback | ❌ (uses username, not BizId) | ⚠️ backend `test_staff.py` covers server; frontend fallback untested (T2) |
| `Register.jsx` `handleSubmit` | ✅ completed | ✅ secondary types / validation | ✅ signup API failed | ✅ around signup | ❌ | ❌ (see gap T4) |
| `Settings.jsx` hosting section | ❌ | ✅ enabling blocked | ❌ | ⚠️ event-dispatch only; LAN test has its own try/catch | ❌ | ⚠️ `HostingComponents.test` covers the modals, not the two-mode `handleCardClick`/`onModeChange` (T5) |
| `loginSync.js` `reconcileBizIdOnLogin` | ✅ consistent / free-tier skip / cloud-ahead / device-ahead / no-cloud-token | ✅ BizID mismatch / no BizID / check skipped | ❌ | ✅ outer + every fetch guarded | ✅ **BizID logged** (local/cloud public_id) | ❌ (see gap T6) |
| `SyncNudgeModal.jsx` | ❌ | ❌ | ❌ | n/a | ❌ | ❌ (T6) |
| `WebLocalOnlyNotice.jsx` | ❌ | ❌ | ❌ | ✅ around `sessionStorage` | ❌ | ❌ (T7) |

### Backend

| File / unit | info | warn | error | try/except | BizId in logs | Tests |
|---|---|---|---|---|---|---|
| `models.py` `User.is_premium` | n/a | n/a | n/a | n/a | n/a | ❌ no assertion on the column/exposure (T8) |
| `migration.py` (runtime migrator) | ✅ per applied column (existing runner) | ✅ existing | ✅ existing | ✅ existing per-DDL guard | ❌ (numeric business ids only, inconsistent) | ⚠️ migrator has generic tests; this column not asserted |
| `alembic/…is_premium.py` | n/a | n/a | n/a | ✅ `_has_column` guard | n/a | ❌ migration not run in CI here |
| `routes/auth.py` `/profile` | (route-level) | — | — | ✅ 404 guard | ⚠️ `[AUTH]` tag present elsewhere, not on `/profile` reads | ❌ no `is_premium` assertion (T8) |
| `services/admin_service.py` `read_audit_log` | ❌ | ✅ **new**: `Audit-log DB read unavailable, using file fallback: %s` | ❌ (downgraded from ERROR+traceback) | ✅ outer try + per-row `detail` guard | ❌ | ❌ no direct `read_audit_log` test (T9) |

**Backend logging baseline:** `logging_config.py` already standardises
`TIME LEVEL component [TAG] message` with a `TAG` class (`[AUTH]`, `[ADMIN]`,
`[SCHED]`, …) and pins noisy third-party loggers to WARNING. A request-scoped
`current_username_var` ContextVar already exists (used by the table-alteration
audit). **There is no `[BizId]` tag yet** — see §4.

---

## 3. Test-coverage gaps (recommended new tests)

| ID | Area | Recommended test |
|----|------|------------------|
| T1 | Support feedback | Backend `test_feedback_submit.py`: `POST /feedback/submit` (multipart, `attach_logs=true/false`) returns 200 and records a ticket; frontend: `authFetch` called with `/feedback/submit` (path, **not** a full URL) — guards the double-URL regression. |
| T2 | Login staff fallback | Frontend `Login`/`AuthContext` test: local `/staff-counters` empty → cloud queried and Staff button shown; `staffLogin` local-fail → cloud-success path saves session + switches to cloud; **wrong password never falls through to cloud** as success. |
| T3 | Signup hosting + setHostingMode | `signup({hosting:'hybrid'})` sets `bizassist_hosting_mode=hybrid`, PUTs mode, provisions cloud token; `setHostingMode('local')` does **not** logout and keeps `API_BASE` local. |
| T4 | Register two options | Only Local / Local + Cloud render; submit forwards `hosting`; navigates to `/` (never `/settings?switch=`). |
| T5 | Settings two-mode switch | Cloud card absent; Local click = instant `setHostingMode('local')` (no preflight); Local + Cloud click blocked-with-toast when cloud offline; legacy `cloud` shows as active "Local + Cloud". |
| T6 | loginSync gating/direction | Free account → **no** nudge; premium + cloud>local → `cloud-to-local` event; premium + local>cloud → `local-to-cloud` event; `SyncNudgeModal` renders the right direction. |
| T7 | Web notice | Web + `is_premium===false` → notice shown; desktop → never; dismiss persists in `sessionStorage`; hidden while `is_premium` undefined (rollout-safe). |
| T8 | Profile is_premium | `GET/PUT /profile` include `is_premium`; defaults false for a new user. |
| T9 | Audit-log fallback | `read_audit_log` with a bad/empty `detail` row returns rows (raw fallback) and does **not** raise; DB-branch failure degrades to the file reader with a single WARNING, no traceback. |

---

## 4. `[BizId]` logging standard (for grep → Elasticsearch + DDP metrics)

**Current state:** neither side stamps a business identifier consistently.
Backend prints numeric `business_id` inline in a few messages; frontend prints
none. Two of the new frontend units (`signup`, `loginSync`) do log the BizID
(`public_id`, e.g. `BA-JABXGD`) in specific lines — those are the model to
generalise.

**Proposed format** — a fixed, greppable field on **every** line:

```
# backend
12:34:56 INFO  services.admin_service  [BizId=BA-JABXGD] [ADMIN] audit read ok (38 rows)
# frontend
💎 [BizAssist:Billing] [INFO] [BizId=BA-JABXGD] [SIGNUP] BizID mirrored to local
```

`grep "\[BizId=BA-JABXGD\]"` then returns one business's full trail across both
tiers, and the field maps 1:1 to an Elasticsearch keyword field (`biz_id`) for
DDP metrics later.

**Yes — richer structured (JSON) lines are the target format**, gated behind a
`LOG_FORMAT=json` env flag (human-readable string above stays the default for
local dev; JSON ships in prod for the log pipeline). Same event, ECS-aligned so
Elasticsearch/Kibana and DDP dashboards can filter and aggregate on any field:

```json
{
  "@timestamp": "2026-07-05T12:34:56.789Z",
  "log.level": "info",
  "biz_id": "BA-JABXGD",
  "service.name": "bizassist-backend",
  "component": "services.admin_service",
  "tag": "ADMIN",
  "event.action": "audit_read",
  "message": "audit read ok",
  "labels": { "rows": 38, "source": "db" },
  "user.name": "Rakshith",
  "trace.id": "c0ed8434-d31…",
  "host": "hf-space",
  "app.version": "1.0.7"
}
```

Guidelines for the JSON form: keep a small **fixed core** (`@timestamp`,
`log.level`, `biz_id`, `component`, `tag`, `event.action`, `message`) on every
line, and put variable data under `labels.*` / `metrics.*` (e.g.
`metrics.sync_delta`, `metrics.duration_ms`) so DDP metrics can be derived
without schema churn. Never log secrets/PII (tokens, passwords, raw customer
rows). Frontend emits the same shape via a `logger` transport that POSTs batches
to a `/telemetry` sink (reusing the existing telemetry pipeline), so web/desktop
lines land in the same index keyed by `biz_id`.

**How to wire it (proposed, not yet implemented):**

- **Backend** — add a `current_bizid_var: ContextVar[str]` next to the existing
  `current_username_var`; set it in the auth dependency (`get_active_user`) from
  the JWT `public_id`; inject it in the `logging_config.py` `Formatter` (a
  `logging.Filter` that reads the ContextVar and adds `record.biz_id`). One
  change, every line gets the tag — no per-call edits. Extend `TAG` with the
  convention. When moving to Elasticsearch, emit the same field as structured
  JSON (`ecs`-style `biz_id`) instead of a formatted string.
- **Frontend** — store `public_id` in the session (`_saveSession` currently
  drops it; add it from the decoded JWT), keep it in a module-level `bizId` in
  `logger.js`, and have `logger.*` prepend `[BizId=…]`. A `logger.setBizId(id)`
  called on login/logout keeps it current.

This is a contained follow-up (logger core + one request dependency); it is
**not** applied in this pass because it touches every log line and warrants its
own review + tests. Say the word and I'll implement it with tests T-log.

---

## 5. Notes / risks carried forward

- **Backend redeploy required** for `is_premium` (runtime migrator adds the
  column at startup; Alembic file kept in parity). Until deployed, `/profile`
  omits it → premium popups and the web notice stay **off** (safe default).
- **Could not run the project toolchain here**: the frontend `node_modules` is
  Windows-built (unusable on this Linux sandbox) and the shell mount served
  truncated file copies, so build/lint/vitest were not run. Every edit was
  verified directly against the real files. Please run `npm run build` + vitest
  and a backend `pytest` locally.
- **Untouched on purpose:** telemetry (`utils/telemetry.js`, `desktop/src/telemetry.js`),
  schedulers/scheduled tasks, the LAN master-server feature, updater, and the
  cloud sync worker — no regressions expected.
- **Staff fresh-device fallback** points that terminal at cloud (its data isn't
  local yet); reversible from Settings → Hosting.

---

## 6. Known issue — username uniqueness vs. business deletion

**Usernames are globally unique** (`User.username unique=True` on both cloud and
local; cloud is the identity/BizID authority). One username = one owner/business.
Business *name* is not unique; the *username* is. Login resolves a username → one
owner; staff log in scoped under the owner (never by a global username).

**Symptom:** after a business's data is deleted from the cloud, re-registering the
same username fails with **"Username already exists"**. Cause: deletion isn't
symmetric — clearing the *data* doesn't remove the *identity* (the `User` row /
username reservation), and deleting on one backend doesn't clean the mirror on the
other. So either the cloud `User` still exists, or the cloud row was removed but
the **local mirror still holds the username** (cloud signup then succeeds and the
local `/signup` mirror 400s). `routes/auth.py::signup` has **no reclaim path** —
any existing username is a hard 400.

**Fix options (not yet implemented — needs product decision):**

1. **Signup self-heal (safe, low-risk):** if cloud signup succeeds but the local
   mirror reports the username exists, *reclaim* the local row (re-key to the new
   BizID + new password hash) instead of 400 — same person, same device.
2. **Real "delete account" (cloud):** remove or tombstone the `User` so the
   username frees; on the next local login, if the cloud identity is gone, offer
   to reset the local mirror. Decide: hard cascade-delete vs. tombstone/reclaim.
3. **Operational unstick (now):** delete the stale `User` row on the cloud
   (admin), or reset the local app data for that username, then re-register.

Recommended: ship #1 now; design #2 with an explicit "delete account" flow +
confirmation, since it is destructive.
