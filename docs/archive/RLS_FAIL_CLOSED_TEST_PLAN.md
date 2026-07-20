# RLS Fail-Closed (S-1) — Test Plan

*Created 2026-06-27. Scope: hardening the Postgres Row-Level Security policies from **fail-open** to **fail-closed**, and proving it doesn't break the app, the migrator, the seeder, or the scheduler before it touches production.*

---

## ⚠️ STATUS: DEFERRED — NOT YET IMPLEMENTED. DO NOT APPLY TO PROD.

> **I deliberately held S-1 (RLS fail-closed).** It is a **live-Postgres access-control change that I cannot test anywhere in the dev/sandbox environment** (the sandbox has no Postgres; the local app runs on SQLite, which has no RLS at all). **If the policy predicate or the system-context exemption is wrong, it can `deny-all` — i.e. take the whole cloud app down.** It must be validated on a **dedicated Postgres staging database** against this plan, with every "MUST PASS" case green, before it is applied to Supabase production.

This document is the test plan to run **when a Postgres staging DB exists**. Implementation (the migration) is written only after the staging environment is ready.

---

## 1. Background — what "fail-open" means here

RLS is enabled with `FORCE ROW LEVEL SECURITY` on every tenant table, and each table has a `tenant_isolation` policy (migration `d7e3a9c6f8b1_create_rls_policies`). Every policy predicate is:

```sql
USING (
    nullif(current_setting('app.current_business_id', true), '') IS NULL   -- ← FAIL-OPEN
    OR business_id = nullif(current_setting('app.current_business_id', true), '')::integer
)
```

The `... IS NULL OR ...` clause means: **when the GUC `app.current_business_id` is unset, the policy returns TRUE for every row → the connection sees ALL tenants' data.** Today this is masked because (a) the HTTP middleware sets the GUC from the JWT on every request, and (b) app-layer `business_id` filters exist. The latent risk (S-1, `PRODUCT_REVIEW.md §B2`): **any future code path that opens `SessionLocal()` without setting the GUC runs with no tenant filter** — a cross-tenant data exposure.

**The fix (fail-closed):** drop the `IS NULL OR` clause so an unset GUC returns **zero rows**. The catch — and the entire reason this needs careful testing — is that several **legitimate** connections run *without* the GUC and must keep working:

- the **startup migrator** (`run_migrations_and_seed`: `create_all`, `_COLUMN_MIGRATIONS` ALTERs, `_check_schema_integrity`, backfills),
- the **seeder** (default users / configs),
- the **APScheduler jobs** (`services/scheduler.py`: daily summary, overdue/low-stock/expiry, hybrid sync tick) — these open `SessionLocal()` directly,
- alembic migrations themselves.

A naive fail-closed policy denies all of these → **boot fails / jobs silently read nothing**. So the fix is two-part: (1) fail-closed predicate, **and** (2) an explicit exemption for system contexts.

## 2. Exemption strategy (decide on staging — test both)

| Option | How | Trade-off |
|---|---|---|
| **A. BYPASSRLS role** (recommended) | Run migrator/seeder/scheduler under a dedicated DB role with the `BYPASSRLS` attribute; the request-path app role does NOT bypass. | Cleanest separation. Requires a second connection string / role. On Supabase confirm whether `postgres` already has BYPASSRLS (if so, RLS never constrains the app today — verify in Test 0). |
| **B. Set a sentinel GUC in system contexts** | System code sets `app.current_business_id` to a value the policy treats as "admin" (e.g. add `OR current_setting(...) = '-1'`). | No role change, but re-introduces a string the policy trusts — weaker; one forgotten `set` = denied job. |
| **C. Per-request only, scheduler sets GUC per business** | Scheduler loops businesses and sets the GUC for each. | More code; doesn't cover migrator/seeder. |

**Recommendation:** Option A. Test 0 below determines whether the app's current `postgres` role already bypasses RLS — that result drives the whole design.

## 3. Test environment

- **Dedicated Postgres staging DB** — a fresh Supabase project (or local Postgres 15) seeded with the full schema via `alembic upgrade head` + the runtime migrator. **NEVER run this plan against the production Supabase.**
- Two tenants seeded: **Biz A** (`business_id = A`) and **Biz B** (`business_id = B`), each with ≥2 rows in: `customers, invoices, invoice_line_items, payments, invoice_payments, b2b_connections, shared_ledgers`.
- A `psql` session (or script) able to `SET app.current_business_id = '<id>'` and `RESET` it, connecting as the **app role** (not a superuser, or RLS won't apply).
- Connection as each candidate role (app role; BYPASSRLS role if Option A).

## 4. Test matrix

Legend: **MUST PASS** = blocks prod. **SHOULD** = fix before GA.

| # | Pri | Precondition | Action | Expected |
|---|---|---|---|---|
| **T0** | MUST | App connects as its prod role | `SHOW is_superuser;` and check `rolbypassrls` for the role; `SET app.current_business_id=''` then `SELECT count(*) FROM customers;` | Establishes baseline: does the app role bypass RLS today? Drives Option A/B. Record the answer. |
| **T1 (repro)** | MUST | Current fail-open policies | GUC unset → `SELECT count(*) FROM customers;` | Returns **all** A+B rows (proves the gap exists pre-fix). |
| **T2** | MUST | Fail-closed applied | GUC unset → `SELECT * FROM customers;` (and invoices, payments, line items) | Returns **0 rows** (no leak when context missing). |
| **T3** | MUST | Fail-closed applied | `SET app.current_business_id=A` → select customers/invoices | Sees **only Biz A** rows; **zero** Biz B rows. |
| **T4** | MUST | Fail-closed applied | `SET ...=A` → `SELECT` a child table (`invoice_line_items`, `invoice_payments`) | Only A's children (EXISTS-scoped); none of B's. |
| **T5** | MUST | Fail-closed applied | `SET ...=A` → `INSERT` a customer with `business_id=B` | **Rejected** by `WITH CHECK` (cannot write cross-tenant). |
| **T6** | MUST | Fail-closed applied | `SET ...=A` → `UPDATE`/`DELETE` a row owned by B (by id) | Affects **0 rows** (can't mutate B's data). |
| **T7** | MUST | Fail-closed applied | B2B tables: `SET ...=A` where A is buyer in a `b2b_connections`/`shared_ledgers` row | A sees rows where it is buyer **or** seller; not unrelated rows. |
| **T8 (system)** | MUST | Fail-closed + Option A role | Run the **startup migrator** path (`run_migrations_and_seed`) against staging | Completes: `create_all`, ALTERs, integrity check, backfills all succeed (no permission denial / no boot halt). |
| **T9 (system)** | MUST | Fail-closed + Option A role | Trigger a **scheduler job** (e.g. overdue-invoice alert) and the **hybrid sync tick** | Reads the intended businesses' rows and writes (alerts/sync) succeed — not silently empty. |
| **T10 (system)** | MUST | Fail-closed | Run `alembic upgrade head` (a no-op rev) on staging | Succeeds (alembic's own connection isn't denied). |
| **T11 (app path)** | MUST | Fail-closed, full app on staging | Log in as A via the API; list customers/invoices; create an invoice; run a report | All work exactly as before (middleware sets the GUC per request). |
| **T12 (cross-tenant API)** | MUST | Fail-closed, full app | As A, request a B-owned resource by id (e.g. `/invoices/<B_id>`) | 404/empty — never B's data. (Re-run the existing `test_connections_security.py` / cross-tenant negative tests against Postgres.) |
| **T13 (sync)** | MUST | Fail-closed | Run the verified Step 3 cloud↔local sync (push + pull + "Sync now") end-to-end | Still works; no rows silently dropped by RLS; deferral/uid logic unaffected. |
| **T14** | SHOULD | Fail-closed | Connection-pool reuse: confirm the GUC is reset/!leaked between pooled requests (set-local vs set) | Tenant A's GUC must not bleed into Tenant B's next request on a reused connection. |
| **T15** | SHOULD | Fail-closed | Performance: EXPLAIN a hot query (invoices list) with the policy active | No pathological plan regression from the policy subselects. |

## 5. The GUC-leak sub-risk (T14 — important)

Today `get_db()` sets `app.current_business_id` on the connection. With `NullPool` (current Postgres config) each request gets a fresh connection, so leakage is unlikely — **but confirm**: if pooling is ever introduced, the GUC must be set with `SET LOCAL` inside a transaction (auto-reset at commit) or explicitly `RESET` in a `finally`, or Tenant A's context can persist onto Tenant B's reused connection. T14 must pass before enabling any non-NullPool config.

## 6. Rollback plan

- The fail-closed change ships as an alembic migration with a tested `downgrade()` that restores the `IS NULL OR` predicate (i.e. reverts to today's fail-open policies).
- **Pre-flight on prod:** take a Supabase backup / PITR snapshot immediately before applying.
- **Blast-radius check:** apply during a low-traffic window; have the `downgrade` (or a one-line `ALTER POLICY` restoring `IS NULL OR`) ready to paste.
- **Detection:** watch backend error rate + a synthetic "list customers" probe right after apply. If the app returns empty/permission errors → roll back immediately.

## 7. Go / No-Go for production

**GO only if:** T0–T13 (all MUST) are green on staging, the chosen exemption (Option A recommended) is in place and proven by T8–T10, the rollback `downgrade` has itself been tested on staging, and a fresh prod backup exists.

**NO-GO if:** any system context (migrator/seeder/scheduler/alembic) is denied, or any cross-tenant read/write (T2–T7, T12) leaks or is wrongly blocked, or T11/T13 (normal app + sync) regress.

## 8. Implementation note (write AFTER staging is ready)

The migration will, per `DIRECT_SCOPED_TABLES` + the child/B2B policies in `d7e3a9c6f8b1`, `ALTER POLICY ... USING (...)` to drop the `nullif(...) IS NULL OR` clause (keep the `WITH CHECK` equivalently tightened), and provision the Option-A BYPASSRLS role for system connections. Keep it Postgres-guarded (`if bind.dialect.name == "postgresql"`) — SQLite has no RLS, so local/hybrid are unaffected (documented as S-2: local trusts the app layer).

---

*Owner: next session, once a Postgres staging DB is available. Until then S-1 remains the top open security item in `SESSION_HANDOFF.md` §9.*
