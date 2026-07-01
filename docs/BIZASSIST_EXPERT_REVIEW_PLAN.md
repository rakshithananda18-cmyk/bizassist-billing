# BizAssist Expert Review Plan

Reviewed: July 2, 2026

This review covers BizAssist as an Indian SME billing, invoicing, stock, sync,
and AI-assisted business intelligence platform. It is based on a direct read of
the current repository, with emphasis on tenant isolation, financial integrity,
sync reliability, test coverage, performance, merchant UX, and code health.

## Executive Verdict

BizAssist has a strong foundation: command-based sale/payment flows, UID-aware
sync, SSE hardening, RLS migrations, offline outbox behavior, and broad backend
and frontend tests are already present.

The product is not production-ready yet for real Indian SME billing. The main
reason is not missing feature surface; it is that a few non-negotiable invariants
are still enforced by convention rather than made impossible to violate:

- Supabase RLS policies are fail-open when the app tenant setting is absent.
- Some financial records can still be hard-deleted.
- Sync can apply deletes to append-only domains.
- Negative-stock prevention exists as a setting but is not enforced in the core
  sale/ledger path.
- Migration reports successful row counts but does not expose skipped-row
  manifests to the operator.

Overall robustness score: 75/100.

## 1. Security and Tenant Isolation Audit

### Finding 1.1: Supabase RLS is fail-open when tenant context is missing

Risk Level: Critical

Specific Finding: The RLS policies allow access when
`app.current_business_id` is not set.

Evidence:

- `backend/alembic/versions/d7e3a9c6f8b1_create_rls_policies.py` creates
  policies with:
  `nullif(current_setting('app.current_business_id', true), '') IS NULL OR ...`
- `backend/main_groq.py` sets `current_business_id_var` best-effort from the
  Bearer JWT in middleware.
- `backend/database/db.py` applies `SET app.current_business_id` only if the
  context variable is not `None`.

Why It Matters: Any code path, background worker, psql session, or missed
middleware path that queries using the application database role without setting
the tenant context can see all rows instead of zero rows.

Recommended Fix:

- Change app-role RLS policies to fail closed when
  `app.current_business_id` is absent.
- Use a separate privileged service/admin role for migrations, maintenance, and
  cross-tenant admin tasks.
- Add Postgres tests proving scoped tables return zero rows when the setting is
  absent and only scoped rows when present.

Priority: P0

### Finding 1.2: Legacy AI/dashboard routes parse authorization manually

Risk Level: Warning

Specific Finding: Several legacy routes manually read the `Authorization` header
instead of using the shared FastAPI dependencies.

Evidence:

- `backend/routes/ai_insights.py::_user_id()` calls `get_active_user()` manually
  with the raw header.
- The newer routes consistently use `Depends(get_active_user)` or
  `Depends(restrict_cashier)`.

Why It Matters: Manual auth parsing creates drift in RBAC, OpenAPI behavior,
tests, and middleware assumptions. It also increases the chance that future auth
changes do not cover every route.

Recommended Fix:

- Convert `routes/ai_insights.py` endpoints to shared auth dependencies.
- Add route-level tests for cashier restrictions and cross-business isolation on
  these legacy endpoints.

Priority: P1

### Finding 1.3: Query-token auth remains available

Risk Level: Warning

Specific Finding: `get_active_user()` accepts a JWT from a query parameter.

Evidence:

- `backend/services/auth.py::get_active_user()` accepts `token: str = Query(None)`.
- Tests confirm query-param token fallback.

Why It Matters: Query-string tokens are more likely to be logged by proxies,
browser history, observability tools, and error reports. SSE tickets are a safer
pattern and already exist.

Recommended Fix:

- Restrict query-token auth to SSE ticket flow only.
- Use short-lived single-use tickets for EventSource connections.
- Keep Bearer headers for normal API requests.

Priority: P2

## 2. Financial Data Integrity Audit

### Finding 2.1: Hard deletes violate append-only financial rules

Risk Level: Critical

Specific Finding: Expenses can be physically deleted, and sync can physically
delete records.

Evidence:

- `backend/core/api/payments.py::delete_expense()` calls `db.delete(exp)`.
- `backend/routes/sync.py::push_changes()` handles `DELETE` by calling
  `db.delete(existing)`.

Why It Matters: Expenses affect P&L and books. Physical deletion breaks audit
history, makes reconciliation harder, and conflicts with the stated
append-only-financials pillar.

Recommended Fix:

- Replace expense delete with `void_expense` or reversal commands.
- Block sync `DELETE` for append-only tables: invoices, invoice payments,
  stock ledger, journal entries, journal lines, expenses, purchases, and payment
  tables.
- For removable master data, prefer `is_active=false` soft state with audit.

Priority: P0

### Finding 2.2: Negative stock prevention is configured but not enforced

Risk Level: Warning

Specific Finding: The business setting `prevent_negative_stock` exists, but
`record_movement()` allows any movement that creates a negative balance.

Evidence:

- Default setting appears in `backend/routes/auth.py`.
- `backend/core/stock/ledger.py::record_movement()` calculates `balance_after`
  and inserts the row without checking whether the balance is below zero.
- Sale invoice creation deducts stock through `SL.record_movement()`.

Why It Matters: Some merchants allow negative stock, but businesses that enable
prevention expect the POS to stop sales that would create impossible inventory.

Recommended Fix:

- Enforce prevention in command handlers before sale, transfer-out, return-out,
  damage, and reservation movements.
- Allow owner-only override with explicit audit metadata if needed.
- Add tests for product-level, batch-level, and godown-level negative stock.

Priority: P1

### Finding 2.3: Core sale and payment commands are strong

Risk Level: Good

Specific Finding: Sale creation and payment recording follow the command
pattern and are mostly aligned with the non-negotiable architecture pillars.

Evidence:

- `backend/core/billing/commands.py::create_sale_invoice()` writes invoice,
  line items, stock ledger movements, initial payment, and accounting posting
  in one session before committing.
- `backend/core/billing/commands.py::record_payment()` is idempotent on
  `(business_id, idempotency_key)` and recomputes paid status from persisted
  payment rows.
- `backend/core/sync/idempotency.py` provides the HTTP replay guard based on
  `X-Client-Request-Id`.

Recommended Fix:

- Keep routes thin.
- Extend the same command discipline to expenses, opening stock, and migration
  write actions.

Priority: P2

## 3. Sync and Data Migration Reliability

### Finding 3.1: Partial import failures are logged but not operator-visible

Risk Level: Warning

Specific Finding: Data import uses per-row savepoints and skips bad rows, but
the API response reports imported counts without a skipped-row manifest.

Evidence:

- `backend/routes/data_transfer.py::_upsert_rows()` and
  `_import_with_remap()` log row skips.
- `import_data()` returns `{"imported": ..., "total": ..., "mode": ...}`.

Why It Matters: A migration can appear successful while silently omitting rows.
For billing data, "mostly imported" is not enough; merchants need a
reconciliation receipt.

Recommended Fix:

- Return `skipped`, `failed_rows`, `failed_reasons`, and per-table totals.
- Add post-import count reconciliation.
- Make the frontend show "completed with issues" instead of success when skips
  exist.

Priority: P1

### Finding 3.2: Migration progress is partly simulated

Risk Level: Warning

Specific Finding: The migration UI animates table progress while a single import
request is in flight.

Evidence:

- `frontend-billing/src/components/hosting/MigrationModal.jsx` starts one
  import `fetch()` and animates progress while waiting.

Why It Matters: During large migrations, simulated progress can create false
trust. Users need accurate progress, interruption handling, and a retry point.

Recommended Fix:

- Add server-side migration job IDs.
- Expose table-level and row-level progress.
- Support resumable or idempotent retry after interruption.

Priority: P2

### Finding 3.3: UID sync architecture is moving in the right direction

Risk Level: Good

Specific Finding: Sync has a shared table map, durable UID matching, FK UID
resolution, LWW conflict logging, and offline outbox semantics.

Evidence:

- `backend/database/sync_map.py` is the shared model map.
- `backend/routes/sync.py` prefers UID lookup and defers child writes when
  parent UID is missing.
- `frontend-billing/src/sync/outbox.js` flushes FIFO with stable request IDs.
- `frontend-billing/src/sync/syncManager.js` sends `X-Client-Request-Id`.

Recommended Fix:

- Add conflict-resolution UX for non-money master data.
- Keep append-only financial entities out of destructive sync operations.

Priority: P2

## 4. Test Coverage and Quality Gate Audit

### Finding 4.1: Test breadth is strong

Risk Level: Good

Specific Finding: The project has meaningful backend, frontend, RLS, SSE,
sync, idempotency, accounting, stock, and migration tests.

Evidence:

- CI runs SQLite backend tests, Postgres RLS tests, frontend Vitest, and
  Playwright.
- Backend tests include `test_sync_idempotency.py`, `test_sse_hardening.py`,
  `test_rls_postgres.py`, `test_stock_ledger.py`, `test_audit_journal.py`,
  and several sync/migration tests.
- Frontend tests include sync manager, outbox, pending invoices, hosting
  components, and realtime E2E.

Recommended Fix:

- Preserve this testing culture.
- Add targeted negative tests for the P0/P1 findings in this document.

Priority: P1

### Finding 4.2: CI references quality tooling but does not enforce coverage/Sonar

Risk Level: Warning

Specific Finding: Sonar configuration expects coverage reports, but CI does not
generate or upload them.

Evidence:

- `sonar-project.properties` points to `backend/coverage.xml` and
  `frontend-billing/coverage/lcov.info`.
- `.github/workflows/ci.yml` runs tests but does not run coverage commands or a
  SonarCloud quality gate.

Recommended Fix:

- Run pytest with coverage XML output.
- Run Vitest with LCOV output.
- Add SonarCloud scan and fail the build on quality gate failure.

Priority: P2

## 5. Performance and Scalability

### Finding 5.1: Some list/report endpoints have N+1 risks

Risk Level: Warning

Specific Finding: Payments listing queries related invoice/customer data inside
the result loop.

Evidence:

- `backend/core/api/payments.py::list_payments()` queries invoice and customer
  per payment row.

Why It Matters: A merchant with years of payments will see latency spikes and
DB load. Reports must feel instant to beat Tally/Vyapar on simplicity and speed.

Recommended Fix:

- Use joins or `selectinload`.
- Add query-count regression tests for payments, invoice listing, party dues,
  and GST reports.

Priority: P2

### Finding 5.2: Large export is memory-heavy

Risk Level: Warning

Specific Finding: Export builds the full tenant JSON payload in memory before
returning it.

Evidence:

- `backend/routes/data_transfer.py::export_data()` loops through tables and
  accumulates `tables_data`.

Recommended Fix:

- Add chunked export/import for large tenants.
- Show row-count estimates before migration.
- Consider streaming export or file-backed export for businesses above a
  threshold.

Priority: P2

### Finding 5.3: SSE has basic backpressure protection

Risk Level: Good

Specific Finding: Realtime SSE has connection limits, bounded queues, heartbeat,
deduplication, and thread-safe broadcast support.

Evidence:

- `backend/services/realtime.py` limits each business to 20 connections and uses
  queue size 100.
- `backend/core/api/realtime.py` sends keep-alive comments.
- `backend/tests/test_sse_hardening.py` covers ticket auth, connection limits,
  and deduplication.

Recommended Fix:

- Add load tests for many businesses and high event rates.
- Add per-business metrics for dropped connections/events.

Priority: P3

## 6. UX and Customer Trust Audit

### Finding 6.1: Offline/sync status UX is unusually thoughtful

Risk Level: Good

Specific Finding: The UI already exposes sync health, pending counts, retry
controls, offline state, and login-triggered sync nudges.

Evidence:

- `frontend-billing/src/layouts/AppLayout.jsx` displays sync health and pending
  queue state.
- `frontend-billing/src/utils/loginSync.js` senses cloud/local divergence.
- `frontend-billing/src/components/hosting/SyncNudgeModal.jsx` gates cloud to
  local sync behind user action.

Recommended Fix:

- Keep sync status visible but compact.
- Add plain-language copy for "saved on this device, not yet backed up".

Priority: P2

### Finding 6.2: Migration/backup trust needs a reconciliation receipt

Risk Level: Warning

Specific Finding: Backup and migration modals show progress and retry, but do
not show detailed before/after reconciliation or skipped-row evidence.

Evidence:

- `BackupModal.jsx` performs export then import with `merge=true`.
- `MigrationModal.jsx` shows progress steps but depends on a coarse import
  response.

Recommended Fix:

- Show before and after counts by table.
- Show skipped rows and downloadable failure details.
- Store a migration receipt in local storage and/or server audit table.

Priority: P1

### Finding 6.3: POS speed is promising but needs field-timing validation

Risk Level: Warning

Specific Finding: The POS architecture is keyboard/barcode oriented, but the
review did not verify measured tap/keystroke timing under real devices.

Evidence:

- `frontend-billing/src/pages/Home.jsx` and sales components are built for POS.
- Barcode search endpoint exists at `/sales/barcode/{code}`.

Recommended Fix:

- Add Playwright/performance scenarios for scan-to-cart, cart-to-paid-print,
  offline save, and reconnect replay.
- Track P95 save-bill latency and barcode lookup latency.

Priority: P2

## 7. Architecture and Code Health

### Finding 7.1: Command pattern is strong in billing, weaker elsewhere

Risk Level: Warning

Specific Finding: Sales and payments use command handlers, but expenses,
product creation with opening stock, and some import writes still carry
transactional domain behavior in route modules.

Evidence:

- `backend/core/billing/commands.py` owns sale/payment/credit-note commands.
- `backend/core/api/products.py` creates product and attempts opening-stock
  ledger movement in route code; ledger failure is logged and product creation
  can still continue.
- `backend/core/api/payments.py` creates and deletes expenses directly.

Recommended Fix:

- Add `core/expense/commands.py`.
- Add product/opening-stock command handler with all-or-nothing semantics.
- Keep route modules as authentication, validation, serialization, and command
  dispatch only.

Priority: P1

### Finding 7.2: Dependency versions are broad

Risk Level: Warning

Specific Finding: Python dependencies are specified with broad lower bounds.

Evidence:

- `requirements.txt` uses constraints such as `fastapi>=0.95.0`,
  `sqlalchemy>=2.0.0`, `chromadb>=0.4.0`, and similar.

Why It Matters: Broad constraints can cause surprise upgrades in CI/cloud
deploys, especially for AI/vector dependencies and FastAPI/Pydantic stacks.

Recommended Fix:

- Add a lockfile or pinned deploy requirements.
- Run scheduled dependency review with tests and vulnerability scanning.

Priority: P2

## Master Priority List

1. P0: Make Supabase RLS fail-closed when tenant context is missing.
2. P0: Remove hard deletes for expenses and other financial records.
3. P0: Block sync `DELETE` for append-only tables.
4. P1: Enforce negative-stock setting in sale, transfer, and return commands.
5. P1: Convert legacy manual-auth routes to shared dependencies.
6. P1: Add migration skipped-row manifest and reconciliation receipt.
7. P1: Move expense and product opening-stock writes into command handlers.
8. P1: Add tests for absent RLS setting, sync delete rejection, expense reversal,
   and partial import failure.
9. P2: Replace simulated migration progress with server-side job progress.
10. P2: Add query-count and performance tests, then optimize N+1 paths.

## Robustness Score

| Dimension | Score |
|---|---:|
| Security and Tenant Isolation | 68/100 |
| Financial Data Integrity | 70/100 |
| Sync and Migration Reliability | 76/100 |
| Tests and Quality Gates | 82/100 |
| Performance and Scalability | 72/100 |
| UX and Customer Trust | 78/100 |
| Architecture and Code Health | 80/100 |

Overall BizAssist Robustness Score: 75/100.

One-line verdict: BizAssist is a promising beta-grade foundation, but it should
not be treated as production-ready for Indian SME billing until RLS is
fail-closed and append-only financial invariants are enforced everywhere.

## Suggested Issue Titles

- P0: Make tenant RLS fail closed when `app.current_business_id` is missing
- P0: Replace expense hard delete with append-only void/reversal command
- P0: Reject sync deletes for invoices, payments, stock ledger, journal, and expenses
- P1: Enforce `prevent_negative_stock` in sale and stock movement commands
- P1: Convert legacy AI insight endpoints to shared FastAPI auth dependencies
- P1: Return skipped-row manifests from data-transfer import
- P1: Add migration reconciliation receipt to the hosting modals
- P1: Move product opening-stock writes into an atomic command handler
- P2: Add server-side migration jobs with real table/row progress
- P2: Add query-count tests and remove payment/report N+1 queries
