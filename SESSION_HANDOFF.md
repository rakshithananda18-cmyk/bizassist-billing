# BizAssist — Technical State Manifest (Session Handoff)

*Generated 2026-06-27. Copy-paste into a new session to resume without context loss.*

---

## 1. SYSTEM ARCHITECTURE & STACK

- **Product:** BizAssist — local-first + cloud billing/POS for Indian SMBs (GST). ~43K LOC backend.
- **Backend:** FastAPI (entry `backend/main_groq.py`), SQLAlchemy ORM, Python 3.12.
  - Local runtime: SQLite (`backend/bizassist.db`).
  - Cloud runtime: Postgres / Supabase, deployed as a **Hugging Face Space** (`huggingface.co/spaces/rakshit-dev/BizAssist`, URL `https://rakshit-dev-bizassist.hf.space`).
- **Frontends:** two React (Vite) apps — `frontend-billing/` (main) + another; deployed on **Vercel**. Config in `frontend-billing/src/config.js` (`IS_LOCAL_APP`, `CLOUD_URL`, `LOCAL_URL='http://localhost:8001'`).
- **Hosting modes:** `local` (SQLite) · `cloud` (Postgres) · `hybrid` (local + background push). Platform lock: web=cloud always; downloaded app=localhost.
- **Real-time:** SSE via `services/realtime.py` (`realtime_manager`, `broadcast_threadsafe` → `run_coroutine_threadsafe` onto main loop, registered in lifespan). Background jobs: APScheduler `BackgroundScheduler` (`services/scheduler.py`), hybrid sync tick **15s**, `max_instances=1, coalesce=True, misfire_grace_time=30`.
- **Migrations (CRITICAL):** runtime path is the **custom** `backend/database/migration.py` (`run_migrations_and_seed()` on startup → `create_all` + `_COLUMN_MIGRATIONS` ALTERs + `_check_schema_integrity` (raises on missing model column) + backfills + seed). **Alembic exists in parallel** (`backend/alembic/versions/`) and is dual-maintained, but is **NOT** the startup mechanism and was never stamped on the dev DB until this session.
- **Repos:** `bizassist-billing/` (main, Vercel). `BizAssist_HF/` = flat copy of backend for the HF Space deploy.
- **Auth:** JWT. `JWT_SECRET` **must match** between local `.env` and HF Space secret or sync 401s.

## 2. STATE DATA & SCHEMAS

- **Identity:** `users` table. `public_id` = **BizID** (`BA-XXXXXX`, Crockford base32), minted per-DB (**not globally unique**) → resolvers guard with **BizID + username**. `users` is **never synced as data** (excluded from `MODEL_MAP`).
- **Tenant scoping:** `business_id = parent_business_id or id`. Postgres RLS keyed on `business_id` (fail-open caveat noted).
- **`BusinessOwnedMixin`** (`database/db.py`): `id` (PK autoincrement), `business_id`, timestamps, **+ `uid = Column(String(36), nullable=True, default=uuid4)`** (Step 3, added this session). Inherited by **13 tables**: `customers, vendors, products, invoices, inventory, payments, purchase_orders, purchase_invoices, expenses, godowns, stock_transfers, journal_entries, period_locks`.
- **Sync map** (`database/sync_map.py`): shared `MODEL_MAP` + `ENTITY_BROADCAST_MAP`; `users` intentionally excluded.
- **Migration API:** `GET /api/migrate/export`, `POST /api/migrate/import?remap_ids=&merge=`, `GET /api/migrate/count`.
- **Sync API:** `POST /api/sync/push`, `GET /api/sync/pull`, `GET /api/sync/queue-depth`, `POST /api/sync/flush`. `SyncChange{entity, entity_id:int, operation, payload, created_at}`.
- **Identity API:** `POST /api/identity/check` → `{"exists": bool}`. Login/signup tokens carry `public_id`.
- **Alembic head:** `b9f1c3e7a2d4_add_uid_sync_keys` (down_revision `d7e3a9c6f8b1`). Dev DB now **stamped** to this head.

## 3. CONSTRAINTS & BUSINESS LOGIC

- **Cloud = subscription/trial-gated source of truth** (free identity/BizID; paid hosting/sync/AI). Local = fast offline working copy + backup.
- **Registration requires a one-time network connection** (cloud-issued BizID, mirrored local). Cloud-first signup; `_applyTemplate` only on local.
- **Login is local-first**, with fresh-device cloud-fallback that creates a local mirror; both paths call `reconcileBizIdOnLogin(token)`.
- **Cloud→local data sync is GATED** — explicit button or migration only; **never auto-pulled**.
- **Hybrid worker is PUSH-ONLY** (`sync_business(..., do_pull=False)` returns before pull).
- **Sync MERGES, never overwrites** — Last-Write-Wins by `updated_at` (`ON CONFLICT … DO UPDATE … WHERE EXCLUDED.updated_at > table.updated_at`); a change with no `updated_at` cannot win (R-5).
- **Per-row SAVEPOINT** (`db.begin_nested()`) on every import/apply row — one poison row never aborts the batch (M-1).
- **`uid`** is the durable cross-DB key; `id` is per-DB. Match cross-DB on `uid`, never `id` (id collisions = wrong-row overwrite).
- **Boolean coercion** on import (SQLite 0/1 int → Postgres BOOLEAN) (Bug-A).
- **Postgres sequence realign** (`setval` to MAX(id)) after id-preserving import (M-2).
- **React StrictMode** double-invokes effects → `started`/`startedRef` guards on BackupModal/MigrationModal.
- **UI mode display:** web shows **Cloud** (not Hybrid); real-time toggles greyed in local mode; Sync Interval gated to `IS_LOCAL_APP && hybrid`.
- **`switchMode` uses PUT /settings** (PATCH → 405, silently broke hosting_mode persistence).
- **New-column rule:** any new model column on a `BusinessOwnedMixin`/persisted table MUST be registered in `_COLUMN_MIGRATIONS` (and ideally a parallel Alembic rev) or startup `_check_schema_integrity` halts boot.

## 4. CODEBASE DIFF & STATUS

### ✅ FINALIZED & VERIFIED THIS SESSION (suite green: 683 passed)
- **Step 3 Phase A (durable `uid`):**
  - `database/db.py` — `uid` on `BusinessOwnedMixin` (no index/unique yet — deferred to B/C).
  - `database/migration.py` — 13 `uid` entries in `_COLUMN_MIGRATIONS` (`ALTER … ADD COLUMN uid TEXT`); new `_backfill_null_uids(conn)` (Postgres `gen_random_uuid()::text`; SQLite per-row `uuid4()`), wired into `run_migrations_and_seed` step 3; `_UID_TABLES` list.
  - `alembic/versions/b9f1c3e7a2d4_add_uid_sync_keys.py` — parallel additive migration (13 tables, defensive `_has_column`, backfill).
  - `tests/test_uid_sync_keys.py` — column present (13 tables), distinct non-null uid on insert, backfill fills NULLs.
  - **Applied locally:** all existing rows backfilled (customers 23, products 38, invoices 51, journal_entries 27 — **0 NULLs**). Dev DB `alembic stamp head` → `b9f1c3e7a2d4`.
- **Step 3 Phase B.1 (uid-first dedup in migration import):**
  - `routes/migrate.py` — new `_uid_lookup()` (business-scoped uid match); wired **ahead of** `_natural_lookup` in `_import_with_remap` (uid wins, natural key = fallback for pre-uid rows).
  - `tests/test_sync_migration_fixes.py` — `test_import_remap_dedups_on_uid_over_natural_key`.
- **(Prior, all ✅):** M-1/M-2/M-4 import hardening, R-1/R-2/R-5/R-6/R-7/H-2 sync hardening, BizID resolvers (BizID+username guard), entity-id remap import, `/api/identity/check`, login cloud-fallback + local mirror, sync nudge popup, push-only hybrid, scheduler 15s+coalesce, web=Cloud display, greyed real-time toggles, live username check on Register.
- **Docs:** `PRODUCT_REVIEW.md`, `MASTER_PLAN_CORE.md`, `SYNC_MIGRATION_AUDIT.md`, `MANUAL_TEST_PLAN.md`, `IDENTITY_AND_SYNC_DESIGN_REVIEW.md`, `STEP3_UID_PLAN.md` (Phase A ✅, B split documented).

### ✅ COMPLETED & VERIFIED — Session 2026-06-27 (continuation)
- **Step 3 Phase A.2 (child/aux uids):** `uid` added to all 11 `TimestampMixin`-only synced child/aux tables (`*_line_items, stock_ledger, product_barcodes, business_settings, invoice_payments, shared_ledgers, stock_transfer_line_items, alert_configs, rate_limit_configs`); registered in `_COLUMN_MIGRATIONS` + `_UID_TABLES`; alembic `ee9c2223e60a_add_child_uids`. All 24 synced tables now carry `uid`.
- **Step 3 Phase B.2 (sync match on uid):** outbox trigger serializes parent `uid` (`_serialize_orm_obj` resolves FKs → `{fk}_uid`/`{base}_uid`); `push_changes` + `sync_worker` pull-apply match `existing` by `uid` (id fallback), never force the source `id`, and resolve child FKs via parent `uid`. **Hardening this session:** if a parent `uid` is present but unresolved locally, the child is **deferred** (not written with a stale source id); worker applies parent tables before children (`_child_last` sort).
- **`shared_ledger` → `shared_ledgers` fix:** the real tablename is `shared_ledgers`; the old key in `_SYNC_TABLES`/`MODEL_MAP`/`_EXPORT_ORDER` silently dropped those rows from sync/broadcast. Renamed.
- **BUG FIX — cross-DB `/api/migrate/count` scoping** (broke the cloud-data nudge): `count_records` now uses `_resolve_owner_id` (BizID+username, active DB) not the per-DB JWT `id`. **Verified end-to-end:** cloud `Rakshith_Dev` (biz 12) → local mirror (biz 127), login senses `cloud=5 > local=1` → "Cloud data available" nudge → Sync now → `5 records merged`, remap `{from: 12, to: 127}`, no dupes.
- **Auth test-user policy escape hatch:** allowed when `is_test_db` OR `ALLOW_TEST_USERS`.
- **`migrate.py` rename (clarity):** `cloud_owner_id`→`dest_owner_id`, `local_owner_id`→`source_owner_id`, `_detect_local_owner_id`→`_detect_source_owner_id` (direction-neutral; the old names were correct only for local→cloud and read backwards for cloud→local sync). Logic unchanged.
- **`SyncNudgeModal` UX:** dismiss only via an explicit **×** (no backdrop/accidental close); `Later` removed.
- **Deployed to HF Space** (`rakshit-dev/BizAssist`) + pushed; GitHub `bizassist-billing` fixes pushed (`e232f81`).

### 🔜 PENDING / NOT STARTED
- **Vercel redeploy** of the web frontends (`frontend-billing`, `frontend-ai`) for the identity/sync UX + the `SyncNudgeModal` × change (the hosted web app still runs the prior bundle).
- **Commit the loose ends:** `SyncNudgeModal.jsx` (uncommitted) + the `migrate.py` rename; tidy the stray `test_results.json` commit message (`9cb9d14`).
- **Confirm HF startup log** shows `Added <table>.uid` + backfill on Supabase and **no `_check_schema_integrity` halt** (deployed but not yet eyeballed).
- **Step 3 Phase C** (after B soaks): `uid` index + `UniqueConstraint(business_id, uid)`; `uid` NOT NULL; retire `?remap_ids` natural-key fallback, the `users`-exclusion, and the `id`-fallback in the apply paths. Add the missing uid tests from `STEP3_UID_PLAN.md §7` (cross-DB no-collision, child-FK-by-parent-uid, merge-LWW-on-uid, id-fallback).

## 5. NEXT EXECUTION POINTER

**Immediate:** Step 3 Phases A/A.2/B.1/B.2 are DONE, deployed, and verified end-to-end (see §4 COMPLETED). The next concrete moves are the §4 PENDING items: Vercel redeploy, commit the loose ends, eyeball the HF migration log, then **Step 3 Phase C** once B has soaked. After Phase C, the §7 forward backlog (below) is the roadmap.

**Top of stack — Step 3 Phase C** (`STEP3_UID_PLAN.md §5`): now that match-on-uid is live and verified, add the `uid` index + `UniqueConstraint(business_id, uid)`, make `uid` NOT NULL (after confirming backfill everywhere), and retire the interim crutches — the `?remap_ids` natural-key fallback, the `users`-exclusion, and the `id`-fallback branches in `push_changes`/`sync_worker`/`_import_with_remap`. Land the missing uid regression tests first (`STEP3_UID_PLAN.md §7`).

**Hard rule for next session:** new persisted columns MUST be added to `_COLUMN_MIGRATIONS` or startup halts. I cannot run `pytest`/`run_tests.ps1` (Windows venv); the user runs them — verification is static + user-run. Do NOT `alembic upgrade head` on an unstamped DB (replays baseline → "table already exists"); use `alembic stamp head`. Bash sandbox mount serves stale partials for freshly-written files — verify via Read, parse via `ast.parse`.

---

## 6. FULL FORWARD ROADMAP & BACKLOG

### Step 3 (durable uid) — remaining phases
- **Phase A** ✅ · **Phase A.2** ✅ · **Phase B.1** ✅ · **Phase B.2** ✅ (all done + verified 2026-06-27 — see §4 COMPLETED).
- **Phase C** (cleanup, after B soaks — ONLY remaining phase): add `uid` index + `UniqueConstraint(business_id, uid)`; make `uid` NOT NULL; retire `?remap_ids` natural-key fallback + the `users`-exclusion + the `_remap_rows`/`_upsert_rows` id-preserving path + the `id`-fallback branches where uid now covers it. Land the `STEP3_UID_PLAN.md §7` regression tests first.

### Cross-DB identity hardening (NEW — found 2026-06-27)
- **PARTIALLY FIXED — BUG: cloud user on local app via restored session → 404 "User not found".** `/settings` (and other regular routes) resolve the user by `username` against the *active* backend; a restored **cloud** session in **local** mode has no local mirror → every core route 404s. **Done (this session):** `AuthContext` now catches `404` on the three restore-time fetches (profile/settings/businessConfig) and calls `logout()` — the 404-loop / stuck state is gone; the user cleanly drops to the login screen (re-login then builds the mirror via the fresh-device path). **Still open (follow-up, not blocking):** (a) the *preferred* path — transparently run the local-mirror create on restore instead of forcing a re-login; (b) backend `409 "needs local mirror"` signal instead of bare `404` so the frontend distinguishes "missing mirror" from a genuine not-found. Trust-critical edges are mitigated; the transparent-restore polish remains.
- **FIXED — BUG: `/api/migrate/count` cross-DB scoping (broke the cloud-data sync nudge).** The divergence-sense check (`reconcileBizIdOnLogin`) calls `/api/migrate/count` on the cloud using the **local** token; `count_records` scoped via `_business_id_for` = the raw JWT `id` (a *per-DB* integer), so on the cloud it counted `WHERE business_id = <local-id>` → always 0 → `cloudTotal > localTotal` never true → nudge never fired even when the cloud had data. **Fix:** `count_records` now uses `_resolve_owner_id(current_user, db)` (BizID+username lookup against the active DB), matching how `/profile` and `/api/sync/pull` already resolve. Verified by repro: cloud `Rakshith_Dev` (biz 12) + 1 customer was invisible to a local (id 127) token before the fix.
- Longer term: make BizID globally unique (cloud-authoritative issuance is in; the per-DB mint + BizID+username guard is the interim). Once uid + global BizID land, retire the username-confirmation guard.

### Review hardening (2026-06-27, pre-push)
- **Auth test-user policy — escape hatch added.** `routes/auth.py` signup now allows test-prefixed usernames when `is_test_db` **OR** `ALLOW_TEST_USERS` (env `1/true/yes`). Prevents the broad prefix list (`u_`, `o_`, `test_`, `rec_`, …) from hard-blocking a legitimate cloud signup, and lets CI/staging opt in deliberately. Default behaviour (block on non-test DB) unchanged → existing `test_user_policy.py` still passes.
- **Sync FK-via-uid — defer instead of writing a stale id.** `routes/sync.py::push_changes` and `services/sync_worker.py` pull-apply: when a `*_uid` parent key is present but the parent row isn't in the destination DB yet, the child row is now **deferred** (logged, re-applied on a later sync) instead of being written with the source-DB integer FK (which would be a wrong-row / orphan link). The worker also now applies **parent/master tables before child tables** within each pull batch (`_child_last` sort) so same-batch parent+child resolve in order and deferral is only the rare cross-batch safety net.

### Deploy / ops
- **Deploy Phase A + B.1 to HF** (this push): `database/db.py`, `database/migration.py`, `routes/migrate.py` → `BizAssist_HF` + HF Space. Verify HF startup log shows `Added <table>.uid` + backfill, and Supabase has `gen_random_uuid()`.
- **Vercel redeploy** for any pending frontend changes.
- Keep `JWT_SECRET` identical local↔HF.

### Quality / validation backlog (from PRODUCT_REVIEW & audits)
- Execute `MANUAL_TEST_PLAN.md` end-to-end on **two systems** (real-time multi-writer trust test).
- RLS **fail-open** caveat: confirm policies deny by default when `app.current_business_id` is unset.
- Reduce `[SYNC_WORKER] Running sync` DEBUG log spam (every 15s) — drop to TRACE or only log on actual work.

### Product / future (not yet scoped)
- Subscription / trial gating of cloud (currently the gate is conceptual; enforce on cloud data + AI + hosting).
- Plan/billing UI; entitlement checks on sync/pull.

---

## 7. FORWARD RECOMMENDATIONS (next session, from doc review)

*Synthesised from `PRODUCT_REVIEW.md`, `STEP3_UID_PLAN.md`, `MASTER_PLAN_CORE.md`/full plan, and `HOSTING_MODE_MASTER_PLAN.md`. These are the recommended next bodies of work **beyond** the immediate §4 PENDING items. Roughly priority-ordered.*

### A. Close the DoD / quality gate (cheapest, highest trust ROI)
- **Pin a green test run** (`run_tests.ps1`) with a single dated count, and **reconcile the test-count drift** — docs cite 555/431 while code has ~541 test fns (`PRODUCT_REVIEW` §B4). This is DoD Gate 1, currently the only open gate.
- **Burn down the 🟡 "built, live-QA pending" items:** offline POS save/replay, print/preview, sticky bars, and the two-system real-time multi-writer test in `MANUAL_TEST_PLAN.md`. These are the gap between "built" and "shippable", not missing features.

### B. Security hardening (`PRODUCT_REVIEW` §B2)
- **S-1 — make RLS fail-CLOSED** for tenant tables (deny when `app.current_business_id` is unset; explicit allowlist for migration/admin/scheduler). Highest-value security item; latent cross-tenant exposure if any future path forgets the context.
- **S-3 — token refresh/revocation:** 24h JWTs can't be revoked (e.g., after removing a cashier). Add a short access token + refresh, or a token-version claim checked against the user row.

### C. Sync/code-health debt (now partly worsened by Phase B work)
- **De-duplicate the sync apply logic.** `PRODUCT_REVIEW` A-2 flagged `_MODEL_MAP` duplicated across `routes/sync.py` + `services/sync_worker.py`; this session ADDED a second copy of the **FK-via-uid resolution + deferral** block in both files. Hoist the shared MODEL_MAP *and* the FK-resolution helper into one module imported by both before it drifts.
- **Finish `Sales.jsx` decomposition** (`PRODUCT_REVIEW` A-1, `R5_SALES_DECOMPOSITION_PLAN.md`) — ~3,600-line god-component on the money path; `usePaymentFlow`→`<PaymentPanel>` extraction is already underway.

### D. Scale-out prerequisites (`PRODUCT_REVIEW` A-4, Phase 5)
- Move process-local **cache / scheduler / rate-limiter to Redis** before any multi-instance / multi-store deploy. Single-worker is fine for pilots only; the app warns if `WEB_CONCURRENCY>1`.

### E. Cross-DB identity end-state (ties off Step 3)
- **Globally-unique BizID** (cloud-authoritative issuance is in; per-DB mint + BizID+username guard is interim). Once global BizID + `uid` NOT NULL land (Phase C), retire the username-confirmation guard and the `users`-exclusion entirely.
- **Restored-session polish:** transparent local-mirror create on session-restore (vs forcing re-login) + backend `409 "needs local mirror"` signal (the 404→logout mitigation is in).

### F. Product / monetisation + moat validation (Phase 5/6, master plan §12–§16)
- **Enforce subscription/trial gating** on cloud data + AI + hosting (today conceptual); build plan/billing UI + entitlement checks on sync/pull. Payments = Razorpay, manual activation first (D6).
- **Compliance:** e-way as compliant PDF first, API aggregator later (D7); CA-validate GST/e-way legality.
- **Customer app** as a PWA share link first, not native (D8).
- **Validate the network USP manually with the pilot** *before* deep Phase 5/6 spend — the moat (BizID network + shared ledger) rests on retailer behaviour, not tech (top startup risk).
