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

### 🔜 PENDING / NOT STARTED
- **Deploy B.1 + Phase A to HF:** push `database/db.py`, `database/migration.py`, `routes/migrate.py` (+ `sync_map.py`, `scheduler.py` if not already) to `BizAssist_HF` and HF Space. On HF startup, `run_migrations_and_seed` adds uid + backfills via `gen_random_uuid()`. Confirm Supabase has `gen_random_uuid()` (default yes).
- **Vercel redeploy** for frontend identity/sync UX changes (if not already pushed).
- **Step 3 Phase B.2** (the big one) — see Next Pointer.
- **Phase C** (later): `uid` index + `UniqueConstraint(business_id, uid)`; `uid` NOT NULL; retire `?remap_ids` natural-key fallback + `users`-exclusion hack.
- **Phase A.2** (small): add `uid` to TimestampMixin-only synced child/aux tables (`*_line_items, stock_ledger, product_barcodes, business_settings, invoice_payments, shared_ledger, stock_transfer_line_items, alert_configs, rate_limit_configs`) before B.2 needs them.

## 5. NEXT EXECUTION POINTER

**Immediate:** run `& "..\venv\Scripts\python.exe" -m pytest -q` from `backend/` to confirm B.1 green (suite was 683-green before B.1; expect 684). Then **deploy Phase A + B.1 to HF** (files in §4 PENDING).

**Top of stack — Step 3 Phase B.2** (`STEP3_UID_PLAN.md §4`): switch push/pull + merge button from `id`- to `uid`-matching. Requires outbox to carry parent uid. Order:
1. **Outbox/trigger layer** — when enqueuing a child row into `SyncQueue`, add `{<fk>_uid: <parent.uid>}` to the payload.
2. **`routes/sync.py::push_changes`** (line ~160) — match `existing` by `payload.uid` (id fallback); on INSERT do **not** force the source `id`; resolve child FKs via the parent `uid` in the payload.
3. **`services/sync_worker.py`** pull-apply (line ~344) — `existing = db.query(model_cls).filter(model_cls.uid == record["uid"]).first()` (id fallback); insert-if-missing; resolve child FK by parent uid.
4. **(Optional)** route the merge sync button (`_upsert_rows(merge=True)`) through the uid-aware `_import_with_remap` with LWW-update-on-match, so it stops relying on aligned ids.

**Hard rule for next session:** new persisted columns MUST be added to `_COLUMN_MIGRATIONS` or startup halts. I cannot run `pytest`/`run_tests.ps1` (Windows venv); the user runs them — verification is static + user-run. Do NOT `alembic upgrade head` on an unstamped DB (replays baseline → "table already exists"); use `alembic stamp head`. Bash sandbox mount serves stale partials for freshly-written files — verify via Read, parse via `ast.parse`.

---

## 6. FULL FORWARD ROADMAP & BACKLOG

### Step 3 (durable uid) — remaining phases
- **Phase A.2** (small): add `uid` to the `TimestampMixin`-only synced child/aux tables — `invoice_line_items, purchase_invoice_line_items, purchase_order_line_items, stock_ledger, product_barcodes, business_settings, invoice_payments, shared_ledger, stock_transfer_line_items, alert_configs, rate_limit_configs`. Register each in `_COLUMN_MIGRATIONS` + extend backfill. Needed before B.2 can resolve child rows by their own uid.
- **Phase B.2** (the big one): push/pull + merge button match on `uid`. Requires outbox to carry parent uid. (Steps in §5.)
- **Phase C** (cleanup, after B soaks): add `uid` index + `UniqueConstraint(business_id, uid)`; make `uid` NOT NULL; retire `?remap_ids` natural-key fallback + the `users`-exclusion + the `_remap_rows`/`_upsert_rows` id-preserving path where uid now covers it.

### Cross-DB identity hardening (NEW — found 2026-06-27)
- **BUG: cloud user on local app via restored session → 404 "User not found".** `/settings` (and other regular routes) resolve the user by `username` against the *active* backend; a restored **cloud** session in **local** mode has no local mirror → every core route 404s. Fix in frontend bootstrap (`AuthContext` session-restore): after restoring, verify the user exists on the active backend; if not, run the local-mirror create (same as fresh-device login) or drop to the login screen. Optionally backend: a clearer 409/"needs local mirror" signal instead of bare 404. **This is trust-critical — do before wider rollout.**
- Longer term: make BizID globally unique (cloud-authoritative issuance is in; the per-DB mint + BizID+username guard is the interim). Once uid + global BizID land, retire the username-confirmation guard.

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
