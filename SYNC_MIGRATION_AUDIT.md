# Hosting-Mode, Migration & Real-Time Sync — Deep Audit

*Audit date: 2026-06-26 · Scope: the three areas you flagged for "issues and silent breaks" — hosting-mode switching, local↔cloud migration, and cloud real-time sync.*
*Method: static code trace (suite not runnable in this env — see `PRODUCT_REVIEW.md` §B4). Each finding cites file:line.*
**Companion:** [`PRODUCT_REVIEW.md`](PRODUCT_REVIEW.md) · [`HOSTING_MODE_MASTER_PLAN.md`](HOSTING_MODE_MASTER_PLAN.md) · [`MASTER_PLAN_CORE.md`](MASTER_PLAN_CORE.md)

---

## ✅ Resolution status — fixes applied 2026-06-26

| ID | Status | What changed |
|----|--------|--------------|
| M-1 | ✅ Fixed | `_upsert_rows`/`_upsert_users` now use `db.begin_nested()` SAVEPOINTs; per-row failures log at WARNING and no longer roll back the whole import. |
| M-2 | ✅ Fixed | `_reset_sequences()` realigns Postgres id sequences after import (route path now matches the standalone script). |
| M-4 | ✅ Fixed | SQLite branch replaced with `INSERT … ON CONFLICT(pk) DO UPDATE` — no more destructive `INSERT OR REPLACE`. |
| R-1 | ✅ Fixed | `RealtimeManager.set_loop()` + `broadcast_threadsafe()`; lifespan registers the main loop; worker dispatches via `run_coroutine_threadsafe`. |
| R-2 | ✅ Fixed | Worker pull cursor now follows the cloud's own `pulled_at` (cloud-clock), eliminating skew-driven missed pulls. *(In-memory; persists within a run — see note.)* |
| R-5 | ✅ Fixed | Push + pull now refuse to overwrite an existing row when the incoming side has no `updated_at` (logged, kept). |
| R-6 | ✅ Fixed | Corrupt queue payloads are dead-lettered (WARNING + marked) instead of pushed as `payload=None`. |
| R-7 | ✅ Fixed | Single shared `database/sync_map.py` (`MODEL_MAP` + `ENTITY_BROADCAST_MAP`) imported by route + worker — no more drift. |
| H-2 | ✅ Fixed | Offline cycles log a `SyncLog` only on the online→offline transition. |
| Bug-A | ✅ Fixed | **(found in live test 2026-06-26)** SQLite int `0/1` rejected by Postgres `BOOLEAN` columns via raw-SQL import → customers/products/invoices/barcodes/godowns all skipped, then inventory/stock_ledger failed on FK. `_upsert_rows` now coerces BOOLEAN columns to real bools. Also trimmed per-row failure logging to the driver's one-line message (was dumping the full SQL per row — the cause of the slow, noisy import). |
| Bug-B | ✅ Fixed | **(found in live hybrid test 2026-06-26)** Hybrid pull copied the cloud `users` row into local → `UNIQUE constraint failed: users.public_id` (local id=122 and cloud id=7 share the unified BizID), and because the pull commits the whole batch at once, that one row rolled back all 101 changes. Fix: **`users` removed from the sync `MODEL_MAP`** (identity is established by registration/login, never synced as data), **and** the worker pull now applies **per-row SAVEPOINTs** so one bad row can't abort the batch. |
| Push-only hybrid | ✅ Changed | The hybrid background worker is now **push-only** (local→cloud backup); it no longer auto-pulls cloud data down (cloud data is subscription-gated). Cloud→local data sync is now **only** explicit ("Back up now") or via migration. Pull path retained behind `sync_business(..., do_pull=True)` for those gated cases. |
| Login-identity | ✅ Added | After login, a **lightweight BizID consistency check only** (`reconcileBizIdOnLogin` in `utils/loginSync.js`): reads `/profile` on both backends and compares `public_id`; logs on mismatch. **No data pull** — full cloud→local sync stays gated behind the Backup button / migration (cloud data is subscription-gated). Also fixed `switchMode` using `PATCH /settings` (405; route is `PUT`) — which had silently prevented `hosting_mode` from persisting to the DB, so hybrid never engaged — and a pre-existing `IS_LOCAL_APP is not defined` ReferenceError in `AuthContext._saveSession`. |
| R-3 | ✅ Implemented (opt-in) | **Entity-id remap** added as `POST /api/migrate/import?remap_ids=true`: destination assigns fresh ids, foreign keys are rewritten via introspection (`_import_with_remap`), and natural-key dedup (`_NATURAL_KEYS`) makes re-import idempotent. Default path unchanged (id-preserving upsert) so the working flow isn't disturbed. Use remap when merging into an account that already has its own rows. |
| BizID | ✅ Implemented | **BizID-first identity resolution** (D9): `public_id` added to login/signup JWT; `_resolve_owner_id` (migrate) and `_resolve_business_id_by_username` (sync) now match on BizID → username → JWT id. Username remains the bridge for the first migration; `_upsert_users` unifies `public_id` onto the destination owner so subsequent matches use the stable BizID. |
| R-4 | ⏸ Deferred | Journal/hash-chain replication contract — needs the D5 decision (replicate cloud journal down vs re-post on apply). |
| H-1 | ⏸ Deferred | Validated/transactional mode switch via the readiness matrix — larger refactor across settings + `/health`. |

**Tests added:** `backend/tests/test_sync_migration_fixes.py` — partial-import isolation (M-1), upsert-preserves-columns (M-4), cross-thread SSE delivery + no-loop safety (R-1).

**Verify locally:** run `run_tests.ps1` (the suite can't execute in the review sandbox — PyPI blocked, Windows-only `venv/`). R-2's cursor is in-memory; persisting it across restarts and doing the R-3/R-4 design notes are the recommended follow-ups.

---

## TL;DR — where the silent breaks come from

Three root causes explain most of what you're seeing:

1. **Migration silently loses data** — a per-row `db.rollback()` inside a single-transaction import wipes everything imported so far, while the API still reports success. (M-1, Critical)
2. **Real-time pull doesn't reach the browser** — the background sync worker broadcasts SSE events from a worker thread onto queues bound to the main event loop, so the events often never fire. Data lands in the DB; the UI never refreshes. (R-1, High)
3. **Timestamp-based pull cursor drops cloud changes** under clock skew, and cross-DB integer IDs collide. The robust id-cursor pull that already exists in the codebase isn't the one the hybrid worker uses. (R-2 / R-3, High)

Everything below is concrete and fixable. Severity legend: 🔴 Critical · 🟠 High · 🟡 Medium · 🔵 Low.

---

## Severity index

| ID | Area | Severity | One-line |
|----|------|----------|----------|
| M-1 | Migration | 🔴 Critical | Per-row `db.rollback()` in a single-txn import → silent whole-batch data loss; count over-reports. |
| M-2 | Migration | 🟠 High | Live import route never resets Postgres sequences → future inserts collide with imported IDs. |
| M-3 | Migration | 🟠 High | Original PKs forced across DBs → `INSERT…ON CONFLICT`/`REPLACE` can overwrite unrelated cloud rows. |
| M-4 | Migration | 🟡 Medium | SQLite `INSERT OR REPLACE` deletes+reinserts → cascade-deletes children / resets unmapped columns. |
| R-1 | Sync (SSE) | 🟠 High | Worker-thread SSE broadcast onto main-loop queues → pull events silently never delivered. |
| R-2 | Sync (pull) | 🟠 High | Timestamp `last_sync_at` cursor + clock skew → cloud changes silently missed. |
| R-3 | Sync (ids) | 🟠 High | Cross-DB autoincrement IDs forced on push/pull → wrong-record overwrite. |
| R-4 | Sync (books) | 🟠 High | `journal_entries`/`journal_lines`/`period_locks` not in sync map → ledger & hash chain diverge between local and cloud. |
| R-5 | Sync (LWW) | 🟡 Medium | Missing `updated_at` on either side disables LWW → unconditional overwrite of newer data. |
| R-6 | Sync | 🟡 Medium | Corrupt queue payload swallowed (`except: pass`) → change pushed with `payload=None`. |
| R-7 | Sync | 🟡 Medium | Two divergent `_MODEL_MAP`s + two `/sync/pull` implementations → drift; the weaker one is in production. |
| H-1 | Hosting mode | 🟡 Medium | Mode read from per-user JSON settings on every 5s tick; no validation/transactional switch. |
| H-2 | Hosting mode | 🔵 Low | Offline cycles write a `SyncLog` row every interval → unbounded growth; pull cursor coupled to these rows. |
| T-1 | Tests/logs | 🟠 High | Only one migration test; no partial-failure/sequence/id-collision/SSE-delivery tests. Swallowed errors log at DEBUG (off in prod). |

---

## Migration findings

### M-1 🔴 Per-row rollback silently discards the whole import
**Where:** `routes/migrate.py` — `_upsert_rows()` line ~370, `_upsert_users()` lines ~262/~287, inside the loop; commit is once at `import_data()` line ~506.

**What happens:** the import runs as **one transaction** (single `db.commit()` at the end). But each helper catches a per-row error and calls `db.rollback()`:
```python
except Exception as exc:
    logger.debug("migrate/import: row skip in %s ...", ...)
    db.rollback()          # ← rolls back the ENTIRE uncommitted transaction
```
`Session.rollback()` is **not** row-scoped — it discards every insert/update done so far in this import (all earlier tables and rows). The loop then keeps flushing onto a rolled-back session, and the final `commit()` persists only the tail. Meanwhile `count`/`imported` were already incremented for the discarded rows, so the API returns `{"imported": {...}, "total": 397}` while the DB holds a fraction of that. **Silent, and worse because the skip is logged at DEBUG (off in prod).**

**Fix:** use a SAVEPOINT per row so only the bad row rolls back:
```python
try:
    with db.begin_nested():     # SAVEPOINT
        db.execute(sql, filtered)
    count += 1
except Exception as exc:
    logger.warning("migrate/import: row skip in %s (pk=%s): %s", table_name, pk, exc)
    # begin_nested auto-rolls back only this savepoint; outer txn intact
```
Then keep the single outer `commit()`. Add a test that injects one bad row and asserts the other rows still import and `total` matches reality.

### M-2 🟠 Live import route never resets Postgres sequences
**Where:** `routes/migrate.py::import_data` (no `setval`). The standalone `migrate_sqlite_to_postgres.py` (lines ~117–130) *does* reset sequences — the **route path does not**.

**What happens:** rows are imported with their original explicit `id`s. Postgres `id` sequences stay at their old value, so the next cloud-side insert calls `nextval()` → an id that already exists → `IntegrityError` (or a silent `ON CONFLICT DO NOTHING` skip). New cloud records then mysteriously fail or vanish after a migration.

**Fix:** after import, for every table with an `id` sequence run
`SELECT setval(pg_get_serial_sequence(:t,'id'), COALESCE((SELECT MAX(id) FROM <t>),1))`. Reuse the helper already in the standalone script.

### M-3 🟠 Original primary keys forced across DBs
**Where:** `_remap_rows()` (lines ~201–217) only remaps `business_id`/`parent_business_id`/`user_id`. Entity PKs (`invoices.id`, `payments.id`, …) are preserved and upserted via `ON CONFLICT (pk) DO UPDATE` / `INSERT OR REPLACE`.

**What happens:** safe for a *first* local→cloud import into a fresh account. For re-migration or a cloud that already created its own rows, local id=10 **overwrites** cloud's unrelated id=10. The owner-id remap fixed tenancy; entity-id identity is still unsolved.

**Fix (choose one):** (a) treat migration as one-shot into an empty target and guard against re-import; or (b) build a real id-remap table per entity (old→new) during import and rewrite foreign keys (invoice_id, customer_ref, product_id, …) — the heavier but correct path for bidirectional use. Document which mode is supported.

### M-4 🟡 SQLite `INSERT OR REPLACE` deletes then reinserts
**Where:** `_upsert_rows()` SQLite branch (line ~360).

**What happens:** `INSERT OR REPLACE` performs a DELETE+INSERT. Any child rows with `ON DELETE CASCADE` to the replaced row are silently removed, and columns absent from the payload are reset to defaults (not preserved). On cloud→local restore this can quietly drop data.

**Fix:** use `INSERT … ON CONFLICT(pk) DO UPDATE SET …` (SQLite ≥3.24 supports upsert) so existing children and unmapped columns survive.

---

## Real-time sync findings

### R-1 🟠 SSE events from the sync worker never reach the browser
**Where:** `services/sync_worker.py::_safe_broadcast` (lines ~48–60) + `services/realtime.py` (queues created in the request loop) + `services/scheduler.py` (APScheduler `BackgroundScheduler` = worker **thread**).

**What happens:** `run_hybrid_sync` runs in an APScheduler background thread. After a successful pull it calls `_safe_broadcast`, which finds no running loop and does `asyncio.run(realtime_manager.broadcast(...))` — spinning up a **new event loop in the worker thread**. But the subscriber `asyncio.Queue`s live in the **main server loop**. `put_nowait` across loops is not thread-safe and won't wake the main-loop consumer, so the `sync.trigger` event is effectively lost. Result: **cloud→local pull updates the DB, but open tabs don't refresh** — exactly a "silent break."

**Fix:** capture the main loop at startup (`asyncio.get_event_loop()` in `lifespan`) and dispatch with
`asyncio.run_coroutine_threadsafe(realtime_manager.broadcast(bid, event), MAIN_LOOP)`. Add a test/log asserting a subscribed queue receives the event after a simulated pull.

### R-2 🟠 Timestamp pull cursor silently drops cloud changes
**Where:** `sync_worker.py::sync_business` lines ~268–289 (builds `last_sync_at` from local `SyncLog.synced_at` with `offset(1 if queue_items else 0)`); `routes/sync.py::pull_changes` line ~296 (`updated_at > last_sync_dt`).

**What happens:** the cursor is a **local-clock** timestamp compared against **cloud-clock** `updated_at`. If the local machine's clock is even slightly ahead, `updated_at > last_sync_dt` excludes freshly-updated cloud rows → they're **never pulled**. The `offset(1…)` hack also couples the pull cursor to push success-logging, which is fragile.

**Fix:** switch the hybrid worker to the **id-cursor pull that already exists** in `core/api/sync.py` (Slice 2: per-entity `id > cursor`, monotonic, gap-free, clock-independent). See R-7 — you have the right implementation; the worker just calls the wrong endpoint.

### R-3 🟠 Cross-DB integer IDs collide on apply
**Where:** push apply `routes/sync.py` lines ~231–242; pull apply `sync_worker.py` lines ~311–333. Both do `existing = query.filter(id == record_id)` then overwrite/insert with the foreign id.

**What happens:** same identity problem as M-3 but on the **live** path. Two writers (local + cloud/web) on the same business produce overlapping autoincrement ids; an apply then updates the **wrong** record. Single-device hybrid is mostly safe; any second writer corrupts silently.

**Fix:** make synced entities carry a stable global key (UUID or `(business_id, client_seq)`) and match on that, not the raw autoincrement `id`. At minimum, document and enforce single-writer hybrid until then.

### R-4 🟠 The posted ledger & hash chain don't sync
**Where:** both `_MODEL_MAP`s (`routes/sync.py` ~38, `sync_worker.py` ~63) omit `journal_entries`, `journal_lines`, `period_locks`, `idempotency_keys`.

**What happens:** invoices/payments sync, but the **posted double-entry journal and its tamper-evident hash chain do not**. After hybrid sync the two databases hold the same documents but different (or empty) journals → `GET /reports/verify-chain` breaks, Audit Journal differs, and your integrity moat is inconsistent across modes. (Pulled invoices are also `setattr`-applied without running `post_entry`/stock posting, so even derived parity isn't guaranteed.)

**Fix:** decide the contract — either (a) replicate journal tables too (note: hash chains are per-DB ordered, so you'd replicate, not re-post), or (b) re-run posting deterministically on apply within the same atomic write. Given D5 (cloud = source of truth), replicating cloud's journal down to local is the cleaner choice. Add a cross-mode `verify_chain` test.

### R-5 🟡 Missing `updated_at` disables LWW (unconditional overwrite)
**Where:** push lines ~211–213, pull lines ~316–320. LWW only runs when *both* sides have `updated_at`.

**What happens:** if either row lacks `updated_at`, the guard is skipped and the incoming version overwrites the existing one regardless of age — a newer record can be clobbered by a stale one.

**Fix:** treat missing `updated_at` as "cannot resolve" and fall back to a deterministic rule (e.g., keep existing, log a conflict) rather than overwrite. Ensure all synced tables actually populate `updated_at` (`onupdate=utcnow` is on the mixin — verify every synced model uses it).

### R-6 🟡 Corrupt queue payload swallowed
**Where:** `sync_worker.py` lines ~216–219:
```python
try: payload_dict = json.loads(item.payload)
except Exception: pass        # → payload_dict stays None
```
The change is then pushed with `payload: None`; the cloud applies an empty update or skips, silently. **Fix:** log at WARNING with the queue id and mark the item dead-lettered rather than pushing a null payload.

### R-7 🟡 Two pull implementations / two model maps — the weaker one ships
**Where:** `routes/sync.py` `/api/sync/pull` (timestamp, whole-table scan) vs `core/api/sync.py` `/sync/pull` (id-cursor, paged, `has_more`). The hybrid worker calls the former (`{CLOUD_URL}/api/sync/push|pull`). Two `_MODEL_MAP`s also exist and can drift (a table added to one only).

**Fix:** consolidate onto the id-cursor pull and a **single shared `_MODEL_MAP`** module imported by routes + worker. Delete or clearly deprecate the timestamp pull.

---

## Hosting-mode findings

### H-1 🟡 Mode switch isn't a validated transaction
**Where:** `sync_worker.py::run_hybrid_sync` lines ~122–145 reads `hosting_mode` from each user's `settings` JSON every tick; `/health` does the same scan (`main_groq.py`).

**What happens:** the mode is a free-form JSON field with no schema/validation and no transactional "switch" — flipping to `hybrid` mid-write, or a malformed settings blob, is handled only by a broad `except` that logs and continues. Per the plan's `§4 Mode Switching` this should go through the readiness/transition matrix; the runtime path doesn't enforce that.

**Fix:** centralize mode in one validated accessor (enum: local|cloud|hybrid), gate the switch behind the readiness checks already designed in `HOSTING_MODE_MASTER_PLAN.md §4.0`, and log every transition at INFO with from→to.

### H-2 🔵 Offline cycles grow `sync_logs` unbounded
**Where:** `sync_business` writes a `SyncLog` on every failed/again every successful cycle (lines ~181, ~239, ~257, ~367). The pull cursor reads these back with `offset(1…)`.

**Fix:** rate-limit failure logging (e.g., only log on state change online↔offline), and prune `sync_logs`. Decouple the pull cursor from these rows (resolved by R-2's id-cursor).

---

## Tests & logging gaps (your DoD Gate 1 & 2)

**T-1 🟠** Migration has a single happy-path test (`tests/test_migrate.py::test_migration_lifecycle`). Missing, per your own checklist (security & money get negative tests):
- partial-failure import → other rows still land, `total` is truthful (covers M-1);
- Postgres sequence continuity after import (covers M-2);
- cross-DB id-collision does not overwrite a foreign row (covers M-3/R-3);
- SSE delivery: a subscribed queue receives `sync.trigger` after a simulated worker pull (covers R-1);
- clock-skew pull: a cloud row updated "in the past" relative to local cursor is still pulled (covers R-2);
- cross-mode `verify_chain` parity (covers R-4).

**Logging:** the swallowed paths (R-6, M-1 skips) log at **DEBUG**, which is off in production, so failures are invisible. Promote sync/migration data-affecting failures to **WARNING/ERROR with `exc_info`** and the keys to trace them (`business_id`, table, pk, queue id) — matching the `[SYNC]`/`[MIGRATE]` style in `PHASE_COMPLETION_CHECKLIST.md` Gate 2.

---

## Suggested fix order (highest pain-relief first)

1. **M-1** SAVEPOINT-per-row in import (stops silent data loss). *Small, high impact.*
2. **R-1** main-loop SSE dispatch (UI refreshes after pull). *Small, high impact.*
3. **R-2 + R-7** point the worker at the id-cursor pull; one shared model map. *Medium.*
4. **M-2** sequence reset in the import route. *Small.*
5. **R-4** decide & implement journal replication / re-post contract. *Medium.*
6. **R-3 / M-3** stable global keys for synced entities (the real cross-DB fix). *Larger — plan it.*
7. **R-5, R-6, M-4, H-1, H-2** hardening + validation.
8. **T-1** add the negative tests above and promote log levels — then run `run_tests.ps1` and close DoD Gate 1.

Each fix is additive and testable in isolation; none requires a schema rewrite except R-3 (which is the one worth a design note before coding).
