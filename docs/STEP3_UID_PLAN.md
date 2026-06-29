# Step 3 — Durable `uid` keys for synced entities (R-3)

*Plan to make cross-DB sync/migration match on a globally-unique key instead of the per-DB autoincrement `id`. This is the durable fix for entity-id collisions; the current `?remap_ids=true` import path and `users`-exclusion are interim measures.*

> **Do this only after `run_tests.ps1` is green** — it's a schema + match-key change, and you want a passing baseline to catch regressions. Each phase below is additive and independently shippable.

Companion: [`IDENTITY_AND_SYNC_DESIGN_REVIEW.md`](IDENTITY_AND_SYNC_DESIGN_REVIEW.md) · [`SYNC_MIGRATION_AUDIT.md`](SYNC_MIGRATION_AUDIT.md)

---

## 1. Why

`id` is a per-database autoincrement, so local `invoice id=10` ≠ cloud `invoice id=10`. Matching cross-DB on `id` causes wrong-row overwrites and collisions (the "two-ID problem"). The fix: every synced row carries a **`uid`** (UUID4) generated at creation; **sync/migrate match on `uid`**, never on `id`. Keep the integer `id` for fast local joins.

## 2. Scope — which tables get `uid`

The tables in `database/sync_map.py` `MODEL_MAP` (business data), i.e.:
`customers, vendors, products, invoices, invoice_line_items, inventory, payments, stock_ledger, product_barcodes, business_settings, invoice_payments, shared_ledger, expenses, godowns, stock_transfers, stock_transfer_line_items, purchase_invoices, purchase_invoice_line_items, purchase_orders, purchase_order_line_items, alert_configs, rate_limit_configs`.

**Not** `users` (identity is never synced as data — already excluded).

## 3. Phase A — schema (additive, safe) — ✅ DONE 2026-06-27

**Implemented** (`uid` on `BusinessOwnedMixin` + migration `b9f1c3e7a2d4_add_uid_sync_keys`):

- **Scope this pass:** the **11 `BusinessOwnedMixin` tables** only — `customers, vendors, products, invoices, inventory, payments, purchase_orders, purchase_invoices, expenses, godowns, stock_transfers` (the main entities where id-collisions actually bite). The `TimestampMixin`-only child/aux tables (`*_line_items, stock_ledger, product_barcodes, business_settings, invoice_payments, shared_ledger, stock_transfer_line_items, alert_configs, rate_limit_configs`) are deferred to **Phase A.2** so each model carries `uid` consistently before Phase B touches them.
- **No `index` / no `UniqueConstraint` yet** — no `uid` lookups happen until Phase B, so the index lands *with* Phase B's match-key switch; the unique constraint lands in Phase C after backfill is confirmed. Keeps this migration minimal/low-risk.
- **Backfill:** Postgres `gen_random_uuid()::text` (built-in on Supabase/PG13+); SQLite row-by-row `uuid4()` in Python. Idempotent (`_has_column` guard + `WHERE uid IS NULL`).
- **Tests:** `tests/test_uid_sync_keys.py` — column present on all 11 tables, new rows get distinct non-null uid, backfill fills NULLs.
- **Verify on deploy:** run `alembic upgrade head` on **both** local SQLite and HF/Supabase, then `run_tests.ps1`. Confirm Supabase has `gen_random_uuid()` (it does by default).

*Original plan below for reference:*

### 3. Phase A — schema (additive, safe)

1. **Model:** add to the shared owned mixin (`database/db.py → BusinessOwnedMixin`) so every business-owned table inherits it:
   ```python
   import uuid
   from sqlalchemy import String, Column
   uid = Column(String(36), index=True, nullable=True, default=lambda: str(uuid.uuid4()))
   ```
   - `nullable=True` so existing rows/tests don't break; `default` fills it for all new rows automatically (ORM-side).
   - Add a **unique constraint per business**: `UniqueConstraint("business_id", "uid")` (a UUID is globally unique, but scoping to business is cheap insurance and matches RLS).

2. **Alembic migration** (new head):
   - `op.add_column(<table>, sa.Column("uid", sa.String(36), nullable=True))` for each synced table.
   - **Backfill** existing rows: `UPDATE <table> SET uid = <generate> WHERE uid IS NULL`.
     - Postgres: `gen_random_uuid()::text` (pgcrypto) or `md5(random()::text||clock_timestamp()::text)`.
     - SQLite: backfill in Python (loop rows, set `str(uuid.uuid4())`) since SQLite has no UUID function.
   - Create index `ix_<table>_uid` and the `UniqueConstraint(business_id, uid)`.
   - Keep it **idempotent / additive** (no `create_all` rebuild needed; mirrors the existing migration style).

3. **Export** (`routes/migrate.py::_fetch_table`, `_row_to_dict`) already serialises all columns → `uid` flows automatically once the column exists. No change needed.

## 4. Phase B — match on `uid` (the behaviour change)

> **Phase B is split into two shippable increments.**
>
> **B.1 — migration import (✅ DONE 2026-06-27).** The remap import path
> (`routes/migrate.py::_import_with_remap`) now dedups on the durable `uid` FIRST
> (`_uid_lookup`), falling back to the fuzzy natural key (phone/name/invoice_id)
> only for rows that predate the column. This reuses the existing fresh-id +
> FK-rewrite (`id_maps`) + per-row-savepoint machinery, so a matched row is
> reused (its destination id feeds child-FK rewrites) and never duplicated — even
> when its natural key changed. This is the path where the live collision bugs
> occurred. Test: `test_import_remap_dedups_on_uid_over_natural_key`.
>
> **B.2 — sync push/pull + merge button (✅ DONE 2026-06-27).** *Implemented parent `uid` serialization in the outbox trigger layer, uid-based matching in both `push_changes` and `sync_worker` pull-apply, and foreign key resolution via parent `uid` values to prevent wrong-row ID mapping and collisions.*
>
> *Original Phase B spec below for reference:*

### 4. Phase B — match on `uid` (the behaviour change)

Switch the match key from `id` → `uid` in the three apply paths. **Fall back to `id`** when a row has no `uid` (older client) so the transition is safe.

1. **Migration import** (`routes/migrate.py`):
   - `_upsert_rows` / merge: change the conflict target / existence check from PK `id` to `uid`. Concretely, look up `SELECT id FROM <t> WHERE business_id=:b AND uid=:uid`:
     - found → UPDATE that row (LWW for merge);
     - not found → INSERT (let the DB assign a fresh local `id`; keep the incoming `uid`).
   - This **retires the `?remap_ids` FK-rewrite hack** for most tables: children carry their own `uid`, and parent references are resolved by the parent's `uid` (see child handling below).

2. **Cloud push handler** (`routes/sync.py::push_changes`): match `existing = ... WHERE uid == change.uid` instead of `id == entity_id`. The client sends `uid` in the payload.

3. **Hybrid pull apply** (`services/sync_worker.py`): `existing = db.query(model_cls).filter(model_cls.uid == record["uid"]).first()`; insert-if-missing (don't force the cloud `id`).

4. **Child rows / foreign keys:** line items reference their parent by integer FK (`invoice_id`). Cross-DB, resolve the parent by **its `uid`**: when applying a child, look up the local parent row by the parent's `uid` (carried in the export) and set the child's FK to the local parent `id`. Build a `parent_uid → local_id` map per import (same shape as the current `id_maps`, keyed by `uid`).

## 5. Phase C — cleanup

- Once `uid` matching is in and verified, the `?remap_ids` path becomes redundant for same-account merges; keep it only if you still support merging two *independently-created* datasets.
- Make `uid` `nullable=False` in a later migration after backfill is confirmed everywhere.

## 6. Rollout order (each shippable)

1. Phase A schema + backfill migration. Deploy to **both** local and cloud (`alembic upgrade head`). No behaviour change yet.
2. Phase B match-on-uid (with id fallback). Deploy.
3. Soak; confirm sync/migration match on `uid` (logs).
4. Phase C: drop the id fallback + remap hack; `uid` NOT NULL.

## 7. Tests to add (name them in the suite)

- **uid uniqueness & backfill:** after migration, every synced row has a non-null `uid`; `(business_id, uid)` unique.
- **cross-DB no-collision:** two DBs with the *same* `id` but *different* `uid` for different rows → import matches by `uid`, never overwrites the wrong row.
- **child FK by parent uid:** import an invoice + line items where the parent gets a *new* local id → line items resolve to the new parent id via the parent's `uid`.
- **merge LWW still holds on uid:** newer `updated_at` wins when matched by `uid`.
- **id-fallback:** a row with no `uid` still imports (matched by `id`) during the transition.

## 8. Risks / notes

- **Backfill on large tables** can be slow on Postgres — do it in batches if needed; on a slow HF free tier, run during a maintenance window.
- **SQLite has no UUID function** → backfill in Python in the migration.
- **RLS unaffected** — `uid` is just another column; tenant scoping stays on `business_id`.
- **No frontend change** — `uid` is internal to sync/migration; the UI keeps using `id`.

---

*Net effect: the entity-collision class of bugs (wrong-row overwrite, cross-DB id clash) is removed by construction, the `users`-exclusion + `remap_ids` interim measures can be retired, and sync becomes safe for true multi-writer.*
