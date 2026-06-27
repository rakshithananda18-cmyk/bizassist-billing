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
- **Step 3 Phase C part 1 (uid unique indexes)** ✅ — `alembic a1b2c3d4e5f6`, applied to **local SQLite** (693 tests green) **and cloud Supabase** (stamp `ee9c2223e60a` from `aea3a6d76429` → upgrade; pre-flight found zero NULL/dup uids). Plus 3 of 4 §7 regression tests (`tests/test_uid_cross_db.py`). Phase C parts 2 (NOT NULL) & 3 (retire fallbacks) deferred to post-soak.
- **Deployed to HF Space** (`rakshit-dev/BizAssist`) + pushed; GitHub `bizassist-billing` pushed through Phase C part 1. **Suite: 693 passed (local, 2026-06-27).**

### 🟡 IN PROGRESS — Real-Time Sync Robustness Phase 1 (delta push), Session 2026-06-27
- **Goal (`REALTIME_SYNC_ROBUSTNESS_PLAN.md` §5 Phase 1, §10 step 6):** stop the full-list refetch on every SSE event; ship the changed record so clients patch their cache.
- **Backend — DONE:** `services/realtime.py::delta_event()` builds a **backward-compatible** event — still `{type:"sync.trigger", entity}` (un-migrated pages/older bundles keep refetching) **plus** additive `{op, kind, rid, uid, payload}`. `payload` is the **page DTO** (not the raw ORM row) to avoid the ORM↔DTO shape mismatch. **Dedup fix:** `broadcast()` now coalesces only *payload-less* triggers — two distinct deltas on the same entity are never dropped (was a latent data-loss bug for any future delta).
- **Backend call sites — DONE for parties:** `core/api/parties.py` create/update **customer** + **vendor** (4 sites) now `db.refresh()` then emit `delta_event("party", payload=_*_out(obj), kind=.., rid=obj.id, uid=obj.uid)`. No money path touched.
- **Frontend — DONE for Parties:** new `src/sync/applyDelta.js` (pure upsert/delete-by-id, uid-aware); `Parties.jsx` patches `customers`/`vendors` **in cloud mode only**, else falls back to `load()`. **Mode gate:** hybrid/local UI reads the local DB the SSE delta hasn't written → those keep refetch-after-pull. Money path untouched.
- **Tests — `backend/tests/test_realtime_delta.py`** (4): event shape, minimal=pure trigger, payload-less coalesce, distinct deltas NOT coalesced. **User runs `run_tests.ps1` (Windows venv) to confirm green.**
- **Manual cloud-mode check:** two browsers, same business, Cloud mode → add/edit a customer or vendor in one → the other's Parties list updates **without a full refetch** (Network tab shows no `/billing/customers` call on the receiver). Toggle Settings → real-time parties off → no patch.
- **Remaining rollout (each independently shippable):** `products` (Stock/Sales), then money entities `invoices`/`payments`/`purchases` — migrate **only with the two-device soak** (`MANUAL_TEST_PLAN.md`), they're the untestable-here money path. `applyDelta` is generic, so each money page auto-upgrades once its backend sites emit a DTO payload.

### 🐞 BUG FOUND + FIXED in 2-device soak (2026-06-27) — POS cart cross-terminal clobber (gap G5)
- **Symptom:** Cloud mode, two terminals. Added a product to the cart on System 1; opening POS on System 2 (empty) **cleared the cart on both**.
- **Root cause (`Sales.jsx`):** the live POS cart was synced business-wide via `pos.cart_sync` SSE with blind Last-Write-Wins by timestamp. A freshly-opened POS broadcasts its default empty cart with a newer timestamp; the apply-guard checked `remoteTabs.length > 0` (number of bill *tabs*, =1 for a fresh cart) instead of whether any tab has line items, so the empty cart won and wiped the in-progress bill — then ping-ponged both to empty.
- **Fix (frontend-only, no backend redeploy):**
  1. **Anti-clobber guard** — a remote cart with **no line items** can never overwrite a non-empty local cart (and doesn't advance the local clock). `cartHasItems()` + `tabsRef` (stale-closure-free read).
  2. **Per-terminal carts (decision)** — `POS_CROSS_DEVICE_CART_SYNC = false`: the in-progress cart is now **per terminal**; we neither broadcast it to nor apply it from other clients. Per-device localStorage restore (minimized tabs) is untouched. Committed data (invoices/stock/products/payments) still syncs in real time. Rationale: silently shared live carts across terminals are a clobber bug, not a feature; two cashiers need independent open bills.
- **The real USP (not the shared cart):** (a) real-time sync of **committed** business data across terminals — the Phase 1 delta work; (b) a **deliberate** cart hand-off (waiter tablet → counter, "send bill to terminal 2") built on **Phase 4 presence + soft-locks** with explicit intent. Tracked as the productised version of G5/Phase 4 in `REALTIME_SYNC_ROBUSTNESS_PLAN.md`.

### 🟢 MONEY-CORRECTNESS — multi-counter invoice-number collision — IMPLEMENTED 2026-06-27 (pending user test)
- **Was:** HIGH — silent lost sale; blocked multi-counter billing. Full design: `REALTIME_SYNC_ROBUSTNESS_PLAN.md` §9.3.
- **Bug:** `_next_invoice_number` = `INV-{count+1}` per DB → two terminals both mint `INV-1001` for different sales (local: separate SQLite; cloud: concurrent count). Then `create_sale_invoice` treated *same business + same invoice_no* as a retry → 2nd genuine sale **silently swallowed**.
- **Fix shipped (no schema change — prefix lives in the `invoice_id` string):**
  - Backend `core/billing/commands.py`: `_next_invoice_number(db, business_id, counter_prefix)` counts only its own prefix series; `counter_prefix` threaded through `create_sale_invoice` + both routes (`SaleRequest`, `FrontendInvoiceRequest`). Idempotency clarified — `X-Client-Request-Id` outer wall is authoritative; `invoice_no` wall is now benign (per-prefix numbers are unique → no cross-counter merge).
  - Frontend `Sales.jsx`: `getCounterPrefix()` ← per-device `localStorage['pos_counter_prefix']`; `syncTabNames`/`getNextInvoiceNo` number within this terminal's series (also fixes the old prefix-from-global-max bug). UI: **POS Counter Settings → "Counter / Invoice Number Prefix"** (`PosSettingsModals.jsx`).
  - Tests: `tests/test_billing.py::{test_counter_prefix_separates_series, test_two_counters_first_sale_no_collision, test_blank_prefix_defaults_to_inv_series}`.
- **User to verify:** run `run_tests.ps1`; then two terminals with prefixes `C1`/`C2` → bills read `C1-0001` / `C2-0001`, both persist (no swallowed sale). Needs Vercel redeploy for the hosted web client + app rebuild.
- **Mental model:** per-counter prefix = no collisions; request-id idempotency = safe retries.

### 🟢 IMPLEMENTED — POS counter = STAFF-ASSIGNED / login-bound (2026-06-28, plan §9.3a; pending user test)
- **Model (FINAL):** the counter is **assigned to a login**, owner-controlled + server-stored. Why not terminal-bound: this is a **browser app with no reliable device ID** → any "this machine is C1" tag is tamperable local state; the **login** is the only server-trusted identity a cashier can't manipulate at the till. (Supersedes the earlier terminal-pick/localStorage dropdown, now retired.)
- **Backend:** new nullable `users.counter_prefix` (model + `_COLUMN_MIGRATIONS` + alembic `b3c1d5e7f9a2`). Owner sets per staff via `POST/PATCH /staff` (`counter_prefix`, normalised); owner sets own via `PUT /profile` (default `OW`). Returned on `/login` + `/profile`. Cashiers blocked from `/staff` → can't self-assign.
- **Frontend:** `AuthContext` stores `user.counter_prefix`; `Sales.jsx::getCounterPrefix()` uses it (fallback owner→`OW-`, else `INV-`). POS shows a **read-only** `Counter: C1` badge (`CounterMenu.jsx`) — **clickable for owners → `/staff`**; old dropdown + `PosCounterSettingsModal` prefix field removed. Owner manages in **Staff page** (`Staff.jsx`): defines **named counters** (`settings.transactions.counters`) and assigns each cashier via **dropdown** (add-form + per-row select).
- **Local↔cloud number namespacing (§9.3b) — IMPLEMENTED 2026-06-28:** two disconnected DBs each minting `C1-0001` for different sales would clash on migrate (importer's `invoice_id` natural-key would merge them → lost bill). Fix: (1) `getCounterPrefix()` prepends **`LCL-`** on local/hybrid (`hosting_mode != cloud`); cloud stays clean → cloud `C1-0001`, local `LCL-C1-0001` (owner `OW-0001`/`LCL-OW-0001`). Distinct series → migrate inserts, never merges. (2) Backstop: `routes/migrate.py::_import_with_remap` skips the natural-key fallback when the incoming row has a `uid` (uid mismatch = different bill → insert). Test: `test_import_does_not_merge_different_uid_invoices_sharing_a_number`. **Numbers are final at issue — never re-numbered (GST-safe); GST gen only consolidates. >1 local machine → give each `LCL1-`/`LCL2-`.**
- **Pending (next focused build):** owner **Live Counters view** — realtime read-only page; each active POS session publishes a presence snapshot (user, counter, cart total, last activity); owner watches tiles. Needs two-device test. (Plan §9.2 Stage 1.)

### 📦 SESSION 2026-06-28 — CHANGED FILES & DEPLOY CHECKLIST
*Everything from this session, for the git + HF + Vercel push. Backend files must ALSO be copied into `BizAssist_HF/` (the flat backend copy the HF Space deploys from).*

**Backend (→ commit + copy to `BizAssist_HF/`):**
- `database/models.py` — `User.counter_prefix`
- `database/migration.py` — `_COLUMN_MIGRATIONS` entry for `users.counter_prefix`
- `alembic/versions/b3c1d5e7f9a2_add_user_counter_prefix.py` — **new** (parity; runtime migrator auto-adds on startup)
- `core/billing/commands.py` — prefix-aware `_next_invoice_number`; `counter_prefix` in `create_sale_invoice`
- `core/api/sales.py` — `counter_prefix` on `SaleRequest` + `FrontendInvoiceRequest` + both routes
- `core/api/staff.py` — `counter_prefix` in staff create/update/out (+ `_norm_prefix`)
- `routes/auth.py` — `counter_prefix` in `/login` (both blocks), `/profile` GET+PUT, `ProfileUpdateRequest`
- `routes/migrate.py` — §9.3b backstop (skip natural-key merge when row has a `uid`)
- `services/realtime.py` — `delta_event()` + dedup fix (Phase 1 delta push)
- `core/api/parties.py` — emit customer/vendor DTO deltas
- Tests: `tests/test_realtime_delta.py` (new), `test_billing.py` (+3 numbering), `test_staff.py` (+2 counter), `test_sync_migration_fixes.py` (+1 backstop)

**Frontend `frontend-billing/` (→ commit + Vercel redeploy + rebuild desktop app):**
- `src/pages/Sales.jsx` — POS cart per-terminal fix; `getCounterPrefix()` (login-based + `LCL-` namespace); PosTopBar props
- `src/pages/Staff.jsx` — named counters manager + dropdown assignment + Counter column
- `src/pages/Parties.jsx` — delta cache-patch (cloud mode)
- `src/components/sales/CounterMenu.jsx` — **new** (read-only counter badge, owner→/staff link)
- `src/components/sales/PosTopBar.jsx` — counter badge wired
- `src/components/sales/PosSettingsModals.jsx` — removed obsolete per-device prefix field
- `src/contexts/AuthContext.jsx` — store `user.counter_prefix`
- `src/sync/applyDelta.js` — **new** (generic delta list patch)

**Deploy order:**
1. Run `run_tests.ps1` green (Windows venv) — backend was 700 pass; new tests add ~6.
2. `npm install` in `frontend-billing/` (and `frontend-ai/`) — restores `vite`/`vitest`; then build.
3. Commit + push `bizassist-billing` (GitHub).
4. Copy backend files → `BizAssist_HF/`, push HF Space. On boot, runtime migrator adds `users.counter_prefix` to Supabase (confirm log: `Added users.counter_prefix`, no `_check_schema_integrity` halt).
5. Vercel redeploy `frontend-billing` (+ `frontend-ai`).
6. Smoke test: assign cashier counters in Staff; bill on cloud (`C1-0001`) and local (`LCL-C1-0001`).
- **Tests:** `tests/test_staff.py::{test_owner_assigns_staff_counter_prefix_carried_to_login, test_cashier_cannot_change_their_counter_prefix}`.
- **Caveat:** same account on two machines at once shares one series (rare; server still guards numbers). One account = one counter at a time.
- **Deploy:** `users.counter_prefix` migration on BOTH DBs (runtime migrator auto-adds on startup; alembic for parity), **HF redeploy + Vercel redeploy**. Owner with no prefix set bills as `OW-`.
- **Test:** assign cashier A→`C1`, B→`C2` in Staff; each logs in and bills → `C1-0001` / `C2-0001`; cashier has no way to change it.

### 🟢 DECIDED — multi-terminal POS design (2026-06-27, see plan §9)
- **Live cart = PER-TERMINAL** (shipped, §9.1). Cashiers (and the owner's own POS) never share a live cart.
- **Owner oversight = separate READ-ONLY "Live Counters" feed** (§9.2 Stage 1) — each POS session publishes a cart snapshot tagged with cashier + counter label; owner watches live tiles; no write-back, no clobber, no concurrency dependency. Owner *edit/take-over* = Stage 2 (needs soft-lock + version). **No global "sync now"/"grant access" button** — only a contextual "Take over".
- **Concurrency layering (§9.4):** per-terminal carts (done) → `version`/409 optimistic concurrency (Phase 3) → presence + auto soft-lock (Phase 4). Completed posted invoices are immutable (never merged/version-raced).
- **Agreed sequence (§9.5):** invoice numbering (§9.3) **first** → Live Counters Stage 1 → delta-push to money entities → Phase 3 version concurrency → Phase 4 presence/soft-lock + owner Stage 2.

### 🔜 PENDING / NOT STARTED
- **Vercel redeploy** of the web frontends (`frontend-billing`, `frontend-ai`) for the identity/sync UX + the `SyncNudgeModal` × change (the hosted web app still runs the prior bundle).
- **Commit the loose ends:** `SyncNudgeModal.jsx` (uncommitted) + the `migrate.py` rename; tidy the stray `test_results.json` commit message (`9cb9d14`).
- **Confirm HF startup log** shows `Added <table>.uid` + backfill on Supabase and **no `_check_schema_integrity` halt** (deployed but not yet eyeballed).
- **Step 3 Phase C** (after B soaks): `uid` index + `UniqueConstraint(business_id, uid)`; `uid` NOT NULL; retire `?remap_ids` natural-key fallback, the `users`-exclusion, and the `id`-fallback in the apply paths. **uid regression tests (`STEP3_UID_PLAN.md §7`) — 3 of 4 added** in `tests/test_uid_cross_db.py` (cross-DB no-collision, child-FK-by-parent-uid, id-fallback); the 4th (merge-LWW-on-`uid` via the live `push_changes`/`sync_worker` path, vs the id-keyed `_upsert_rows` LWW already covered by `test_merge_lww_keeps_newer_inserts_new`) still TODO. **Run these (user; Windows venv) to confirm green before starting Phase C.**

## 5. NEXT EXECUTION POINTER

**Immediate:** Step 3 Phases A/A.2/B.1/B.2 are DONE, deployed, and verified end-to-end (see §4 COMPLETED). The next concrete moves are the §4 PENDING items: Vercel redeploy, commit the loose ends, eyeball the HF migration log, then **Step 3 Phase C** once B has soaked. After Phase C, the §7 forward backlog (below) is the roadmap.

**Top of stack — Step 3 Phase C** (`STEP3_UID_PLAN.md §5`): now that match-on-uid is live and verified, add the `uid` index + `UniqueConstraint(business_id, uid)`, make `uid` NOT NULL (after confirming backfill everywhere), and retire the interim crutches — the `?remap_ids` natural-key fallback, the `users`-exclusion, and the `id`-fallback branches in `push_changes`/`sync_worker`/`_import_with_remap`. Land the missing uid regression tests first (`STEP3_UID_PLAN.md §7`).

**Hard rule for next session:** new persisted columns MUST be added to `_COLUMN_MIGRATIONS` or startup halts. I cannot run `pytest`/`run_tests.ps1` (Windows venv); the user runs them — verification is static + user-run. Do NOT `alembic upgrade head` on an unstamped DB (replays baseline → "table already exists"); use `alembic stamp head`. Bash sandbox mount serves stale partials for freshly-written files — verify via Read, parse via `ast.parse`.

---

## 6. FULL FORWARD ROADMAP & BACKLOG

### Step 3 (durable uid) — remaining phases
- **Phase A** ✅ · **Phase A.2** ✅ · **Phase B.1** ✅ · **Phase B.2** ✅ (all done + verified 2026-06-27 — see §4 COMPLETED).
- **Phase C** (cleanup, split into 3 parts):
  - **Part 1 ✅ DONE & APPLIED (2026-06-27):** `alembic/versions/a1b2c3d4e5f6_phase_c_uid_unique_indexes.py` — unique index on `(business_id, uid)` (or `(uid)` for child tables), pre-flight guarded against NULL/duplicate uids. Unique *index* (not a constraint) → applies on SQLite + Postgres with no batch rebuild. **Applied to BOTH DBs:** local SQLite (`alembic upgrade head`, 693 tests green) **and** cloud Supabase (`alembic stamp ee9c2223e60a` from `aea3a6d76429`, then `upgrade head`; no NULL/dup → indexes live). Committed to both repos.
  - **Part 2 (TODO, after soak):** make `uid` NOT NULL (alembic migration; verify zero NULLs on both DBs first — pre-flight already confirmed none).
  - **Part 3 (TODO, after soak):** retire `?remap_ids` natural-key fallback + the `users`-exclusion + the `_remap_rows`/`_upsert_rows` id-preserving path + the `id`-fallback branches in `push_changes`/`sync_worker`/`_import_with_remap`.
  - §7 regression tests: 3 of 4 added (`tests/test_uid_cross_db.py`); merge-LWW-on-uid via the live `push_changes`/`sync_worker` path still TODO (needs a sync harness).

### Cross-DB identity hardening (NEW — found 2026-06-27)
- **PARTIALLY FIXED — BUG: cloud user on local app via restored session → 404 "User not found".** `/settings` (and other regular routes) resolve the user by `username` against the *active* backend; a restored **cloud** session in **local** mode has no local mirror → every core route 404s. **Done (this session):** `AuthContext` now catches `404` on the three restore-time fetches (profile/settings/businessConfig) and calls `logout()` — the 404-loop / stuck state is gone; the user cleanly drops to the login screen (re-login then builds the mirror via the fresh-device path). **Still open (follow-up, not blocking):** (a) the *preferred* path — transparently run the local-mirror create on restore instead of forcing a re-login; (b) backend `409 "needs local mirror"` signal instead of bare `404` so the frontend distinguishes "missing mirror" from a genuine not-found. Trust-critical edges are mitigated; the transparent-restore polish remains.
- **FIXED — BUG: `/api/migrate/count` cross-DB scoping (broke the cloud-data sync nudge).** The divergence-sense check (`reconcileBizIdOnLogin`) calls `/api/migrate/count` on the cloud using the **local** token; `count_records` scoped via `_business_id_for` = the raw JWT `id` (a *per-DB* integer), so on the cloud it counted `WHERE business_id = <local-id>` → always 0 → `cloudTotal > localTotal` never true → nudge never fired even when the cloud had data. **Fix:** `count_records` now uses `_resolve_owner_id(current_user, db)` (BizID+username lookup against the active DB), matching how `/profile` and `/api/sync/pull` already resolve. Verified by repro: cloud `Rakshith_Dev` (biz 12) + 1 customer was invisible to a local (id 127) token before the fix.
- Longer term: make BizID globally unique (cloud-authoritative issuance is in; the per-DB mint + BizID+username guard is the interim). Once uid + global BizID land, retire the username-confirmation guard.

### Review hardening (2026-06-27, pre-push)
- **Auth test-user policy — escape hatch added.** `routes/auth.py` signup now allows test-prefixed usernames when `is_test_db` **OR** `ALLOW_TEST_USERS` (env `1/true/yes`). Prevents the broad prefix list (`u_`, `o_`, `test_`, `rec_`, …) from hard-blocking a legitimate cloud signup, and lets CI/staging opt in deliberately. Default behaviour (block on non-test DB) unchanged → existing `test_user_policy.py` still passes.
- **Sync FK-via-uid — defer instead of writing a stale id.** `routes/sync.py::push_changes` and `services/sync_worker.py` pull-apply: when a `*_uid` parent key is present but the parent row isn't in the destination DB yet, the child row is now **deferred** (logged, re-applied on a later sync) instead of being written with the source-DB integer FK (which would be a wrong-row / orphan link). The worker also now applies **parent/master tables before child tables** within each pull batch (`_child_last` sort) so same-batch parent+child resolve in order and deferral is only the rare cross-batch safety net.

### Deploy / ops
- ✅ **HF Space deployed** (2026-06-27): all Step 3 backend (`db.py`, `migration.py`, `models.py`, `core/models.py`, `sync_map.py`, `routes/{auth,migrate,sync}.py`, `services/sync_worker.py`, both alembic uid revs) pushed to `BizAssist_HF` + Space; runtime migrator added `uid` columns + backfilled on Supabase. Phase C part-1 unique indexes applied to Supabase via manual `alembic`.
- ✅ **GitHub `bizassist-billing`** pushed through Phase C part 1.
- 🔜 **Vercel redeploy** of `frontend-billing` + `frontend-ai` for the identity/sync UX + the `SyncNudgeModal` × change (hosted web still on the prior bundle).
- Keep `JWT_SECRET` identical local↔HF (sync 401s otherwise). Keep the Supabase URL **only** in the HF Space secret, not local `.env`.

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

### C. Sync/code-health debt
- ✅ **DONE (2026-06-27):** the duplicated **FK-via-uid resolution + deferral** block is now a single `resolve_parent_fk_uids()` helper in `database/sync_map.py`, called by both `routes/sync.py::push_changes` and `services/sync_worker.py` pull-apply (MODEL_MAP was already shared there per R-7). *Behavior-preserving; needs `run_tests.ps1` + HF redeploy of `sync_map.py`/`sync.py`/`sync_worker.py`.*
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

### G. Product / feature-depth gaps (from `VYAPAR_FEATURE_BENCHMARK.md`)
*Not behind Vyapar on fundamentals; gaps are depth + compliance. (Benchmark is partly stale — accounting reports like Balance Sheet/Day Book/Trial Balance now exist; re-verify before acting.)*
- **Compliance moat (where Vyapar wins — dedicated workstream, not a form field):** live **e-Invoice (IRN + signed QR)** IRP integration; **e-Way Bill** generation (NIC API); GSTR-1 JSON **GSTN-validated**. Currently fields/stubs, not live filing.
- **Merchant must-haves — verify depth & finish:** thermal (58/80mm) + A4 print; WhatsApp/PDF share; **UPI QR on invoice**; Estimate/Quotation→Invoice convert; Delivery Challan; Credit/Debit notes that actually **post stock + ledger**; **barcode label printing** (scanning exists, generating doesn't).
- **Known model limits:** one business per user → **multi-firm / multi-GSTIN** not supported; TCS/TDS, GSTR-2/9 not seen.
- **Frontend maintainability:** `Sales.jsx`/`Purchases.jsx`/`Settings.jsx` heavy files (see §7.C); add shared primitives (`<DataTable>`, `<Money>`, `<Modal>`, an `api/` service layer) to kill duplicated per-page code.

---

## 8. PRODUCTION READINESS CHECKLIST (go-live gate)

*What must be true before charging real merchants. Ordered must → should → later. Sources: `PRODUCT_REVIEW.md`, `PHASE_COMPLETION_CHECKLIST.md`, `HOSTING_MODE_MASTER_PLAN.md`.*

**MUST (block go-live):**
- [ ] **Green test-suite stamp** — `run_tests.ps1` all-green, single dated count pinned in the tracker; reconcile the 555/431/~541 drift (DoD Gate 1, the one open gate). *Current: 693 local green as of 2026-06-27.*
- [ ] **RLS fail-CLOSED** (S-1) before onboarding multiple untrusted tenants on cloud — today policies pass when `app.current_business_id` is unset. App-layer filters cover it now, but one forgetful `SessionLocal()` path = cross-tenant leak.
- [ ] **Secrets hygiene:** `JWT_SECRET` ≥32 bytes and identical local↔HF; Supabase URL/password **only** in the HF Space secret (not local `.env`); **rotate the Supabase password** (exposed in chat/plaintext this session); confirm `.env` stays gitignored (it is).
- [ ] **`ALLOW_TEST_USERS` unset in prod** and prod `DATABASE_URL` does **not** contain the substring "test" (the test-user gate keys off both).
- [ ] **Backups on:** Supabase PITR / automated backups enabled; documented restore drill. Local SQLite backup guidance for downloaded-app users.
- [ ] **Offline-sync live QA on two real devices** (R7b) — the multi-writer trust test in `MANUAL_TEST_PLAN.md`. Soak the Step 3 uid path here.
- [ ] **GST / e-way legality CA-validated** before invoices are filed on (compliance/legal risk, not code).

**SHOULD (soon after launch):**
- [ ] **Observability:** error tracking (e.g. Sentry) on backend + both frontends; HF Space uptime check; alert on sync auto-disable (the 5-consecutive-failure breaker exists — wire it to a notification).
- [ ] **Token refresh/revocation** (S-3) — short access token + refresh or a `token_version` claim, so removing a cashier takes effect < 24h.
- [ ] **Rate-limiting confirmed enforced on cloud** (`rate_limit_configs` present) and CORS allowlist set to the real prod origins.
- [ ] **Reduce sync DEBUG log spam** (`[SYNC_WORKER] Running sync` every 15s → TRACE / only-on-work) so real signal isn't buried.

**LATER (scale / growth):**
- [ ] **Redis for shared state** (cache / scheduler / rate-limiter) before any multi-worker / multi-instance deploy — single-worker is a hard ceiling (A-4); app warns if `WEB_CONCURRENCY>1`.
- [ ] **Subscription/trial gating enforced** on cloud data + AI + hosting (Razorpay, manual activation first — D6) before monetisation.

## 9. SECURITY POSTURE & GAP REGISTER

*Strong foundation (per `PRODUCT_REVIEW` Part A: "Security 🟢 Strong, 1 caveat"). What's solid vs the open gaps, each with status + action.*

**Solid (keep):** JWT HS256 (env secret, 24h) · bcrypt passwords · single-use 30s SSE tickets · RBAC owner/cashier (single-source guard, backend-authoritative, `test_roles.py`) · tenant isolation in depth (app-layer `business_id` + Postgres RLS FORCE, per-table policies, cross-tenant negative tests) · money integrity (posted double-entry, SHA-256 hash chain + `verify_chain`, append-only period locks, two-wall idempotency) · no `eval`/`exec`/`shell=True`/`debug=True`, CORS allowlist, no secrets in git.

**Open gaps:**
| # | Sev | Gap | Status / action |
|---|---|---|---|
| S-1 | 🟠 Med | **RLS fail-open** — policies pass when tenant GUC unset | OPEN, **deliberately deferred** (can deny-all if wrong). Test plan: **`RLS_FAIL_CLOSED_TEST_PLAN.md`**; now **automatable** via `backend/tests/test_rls_postgres.py` (pytest + testcontainers Postgres — no prod/Supabase needed; skips without Docker). Make fail-closed + exempt migration/seeder/scheduler before multi-tenant scale. |
| S-3 | 🟡 Low | **No token refresh/revocation** — 24h JWT can't be revoked early | OPEN. Add refresh or `token_version` claim checked vs user row. |
| SEC-NEW-1 | 🟠 Med | **Supabase DB password exposed** (plaintext in local `.env` + this chat) | ACTION: rotate in Supabase; keep new value only in HF Space secret. |
| SEC-NEW-2 | 🟡 Low | **Test-user gate is substring-based** (`"test" in DATABASE_URL`) + broad prefix list | Mitigated by `ALLOW_TEST_USERS` escape hatch; ensure prod `DATABASE_URL` has no "test" substring and `ALLOW_TEST_USERS` unset. |
| S-2 | 🟡 Low | **SQLite (local) has no RLS** — app-layer only | ACCEPTED for single-merchant local; cloud Postgres is where RLS enforces. Document. |
| S-4/S-5 | 🔵 Info | JWT decoded twice; middleware swallows decode errors | Info only; S-5 pairs with S-1 (unset context must not mean "see all"). |

**Net:** money path and multi-tenant isolation are genuinely strong; the one item to close before widening the tenant base is **S-1 (fail-closed RLS)**, and operationally **rotate the exposed Supabase password**.

---

## 10. MASTER SEQUENCE TO FOLLOW NEXT (ordered)

*The recommended order across everything open. Each step is shippable; do them roughly in sequence (dependencies noted). Plans referenced: `RLS_FAIL_CLOSED_TEST_PLAN.md`, `REALTIME_SYNC_ROBUSTNESS_PLAN.md`, `TESTING.md`, `STEP3_UID_PLAN.md`.*

1. **Land the loose ends (now).** Commit the uncommitted edits (sync de-dup, test scaffolds, test plans, this handoff); push GitHub + HF; **Vercel redeploy** both frontends. Pin a dated green `run_tests.ps1` count (DoD Gate 1) and reconcile the 555/431/693 drift.
2. **Wire CI (cheap, compounding).** Add the GitHub Actions from `TESTING.md`: pytest (SQLite) + `test_rls_postgres.py` (service Postgres) + Playwright. Now every change is gated.
3. **Soak Step 3 (a few days of real two-device use).** Run `MANUAL_TEST_PLAN.md` Scenarios B/C/D; watch logs for `deferring` / `failed to resolve FK`. Confirm idempotent re-sync (no dupes) and unique-index enforcement.
4. **Step 3 Phase C parts 2 & 3** (after soak): `uid NOT NULL`; retire the `?remap_ids`/`users`-exclusion/`id`-fallback crutches. Tests-first (`STEP3_UID_PLAN.md §7`, incl. the 4th merge-LWW-on-uid test).
5. **S-1 — RLS fail-closed.** Make `test_rls_postgres.py` green first (it already automates the matrix), implement the fail-closed migration + system-context (BYPASSRLS) exemption per `RLS_FAIL_CLOSED_TEST_PLAN.md`, validate on Postgres staging/CI, then apply to Supabase with the rollback ready. **Gate before widening the tenant base.** Also: rotate the exposed Supabase password.
6. **Real-time sync robustness** (`REALTIME_SYNC_ROBUSTNESS_PLAN.md`): **Phase 1 (delta push)** 🟡 parties slice landed → **Phase 2 (ordered change-log + gap recovery)** for Firestore-grade reliability → **Phase 3 (optimistic concurrency + field merge)**. Phases 4 (presence) / 5 (CRDT for collaborative surfaces) later.
   - **6a. 🚨 Multi-counter invoice numbering FIRST** (plan §9.3) — money-correctness, blocks multi-counter billing: per-counter prefix via `device_id` + request-id (not invoice_no) idempotency.
   - **6b. Owner "Live Counters" read-only feed** (plan §9.2 Stage 1) — high value, low risk, reuses `pos.cart_sync` redirected to owner-only consumers.
   - Per-terminal carts (plan §9.1) already shipped; owner edit/take-over (§9.2 Stage 2) rides on Phase 3/4.
7. **Scale-out prep:** Redis for cache/scheduler/rate-limiter **and** realtime fan-out + change-log catch-up (needed before any multi-worker deploy; ties into sync Phase 2).
8. **Code-health:** finish `Sales.jsx`/`Purchases.jsx`/`Settings.jsx` decomposition + shared FE primitives (`<DataTable>/<Money>/<Modal>/api layer`).
9. **Product / compliance depth (revenue-gated):** subscription/trial gating (Razorpay), then the `VYAPAR_FEATURE_BENCHMARK` gaps — e-Invoice IRN, e-Way Bill, UPI QR, credit/debit-note posting — and CA-validate GST/e-way.
10. **Pilot validation of the network USP** in parallel throughout — the moat rests on retailer behaviour, not tech.
