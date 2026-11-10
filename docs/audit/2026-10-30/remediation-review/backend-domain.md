# Backend remediation verification — 30 October 2026

This pass verifies **HEAD `6c52792` plus the current unstaged and new files** against
the original audit committed at `f5d715c`. It does not assess HEAD alone. Product
source, user tests and existing audit artifacts were not edited, staged, committed
or reverted by this reviewer. New files in this directory contain the review.

## Verdict

**8 of the 13 backend findings are fixed in current code, 4 are partial, and 1
remains open.** The containment fixes for unsafe AI payments, hash re-sealing and
standalone advances work. Exact stock buckets, carton conversion, catalogue stock
aggregation, catalogue policy and terminal-state protection also work in the
verified scenarios.

The remaining work is material: the new cost migration can erase reported
historical COGS; a zero-cost return can create negative COGS; an order destination
change can suppress GST; the new financial summary still disagrees with legacy
and partial-payment data; and existing databases do not receive the debit-note
unique index. The supplier-payment/refund workflows are still intentionally
unavailable. This is not yet a fully closed financial remediation package.

`fixed` here means the original defect is prevented in reviewed code and synthetic
verification. For BD-01 and BD-09, disabling an unsafe feature is the successful
containment; the fuller feature has not been implemented. No status means existing
merchant data has already been reconciled or a live deployment was verified.

## Status by original finding

| ID | Status | Current result and remaining boundary |
|---|---|---|
| BD-01 | Fixed, contained | Status-only AI mark-paid refuses execution and preserves invoice/payment state. |
| BD-02 | Fixed | Ledger writes, rebuild and self-heal use exact NULL warehouse/batch predicates; cache sum now matches the ledger. |
| BD-03 | Fixed | A ₹120 carton containing 12 pieces becomes 12 units at cost ₹10; product default markup also uses base-unit cost. |
| BD-04 | Partial | Simple full-return overview is correct; deterministic handler/prompt snapshot, mixed legacy receipts and return-adjusted overdue remain wrong. |
| BD-05 | Fixed, contained | Repair leaves the old hash intact and the mismatch alarm remains false/failed. |
| BD-06 | Partial | Stable simple GST head selection works; order/invoice rounding differs and changing buyer state can produce zero GST. |
| BD-07 | Fixed | Create-order denies a hidden-category product ID under the accepted connection's policy. |
| BD-08 | Fixed, test update needed | Terminal mutation is blocked and UI follows the graph; four old integration fixtures still skip required states. |
| BD-09 | Fixed, contained | Standalone advance with no invoice dues is refused before credit balance changes. |
| BD-10 | Partial | Positive newly created cost snapshots work; migration/unknown-cost and zero-cost returns are unsafe. |
| BD-11 | Open | Supplier-payment refusal remains correct; real supplier settlements, linked refunds and return-credit allocations are not implemented. |
| BD-12 | Fixed | Catalogue query uses SUM/GROUP BY across inventory buckets. |
| BD-13 | Partial | DN auto-allocation uses a durable sequence; model-only uniqueness does not protect an upgraded existing table. |

Machine-readable evidence, exact current references and caveats are in
`backend-status.json`. `backend-snapshot.json` records hashes of the reviewed
implementation/test files so a later edit can be distinguished from this result.

## Remaining and newly introduced problems

### 1. P1 — cost migration fabricates zero historical cost (BD-10)

`backend/database/migration.py:314` adds the snapshot with `REAL DEFAULT 0.0`.
SQLite applies that default to every existing row. The new report at
`backend/core/api/reports.py:267` trusts `InvoiceLineItem.cost_price` before the
catalogue fallback, so those zero values are treated as evidence of free stock.
`backend/database/models.py:374` also defaults omitted snapshots to zero. No
Alembic revision for this column was found.

**Current-code proof:** create a predecessor-shaped invoice line, then apply the
exact new DDL. Its missing historical cost becomes 0. An invoice whose prior
catalogue valuation was ₹80 is now reported with **COGS ₹0**, without any source
evidence supporting a change. This is a migration/report regression, not merely
an untested deployment detail.

Unknown historical valuation must remain explicitly unknown/NULL. The report
needs a clear missing-history policy; blindly guessing today's price would also
violate the original audit. Add and test the real upgrade path, then reconcile
history only where documentary evidence exists.

### 2. P1 — returning an originally zero-cost sale creates profit (BD-10)

`backend/core/billing/commands.py:1153` uses
`orig_line.cost_price or product.cost_price`. A legitimate snapshot of zero is
false in Python, so the return gets today's catalogue cost instead.

**Current-code proof:** sell at cost 0, change catalogue cost to ₹40, then return
the entire item. The credit-note line snapshots cost ₹40 and the P&L reports
**net COGS −₹40** after a complete reversal, rather than zero. Preserve zero as a
known value and distinguish it from a genuinely missing snapshot.

### 3. P1 — destination changes can remove all GST from B2B completion (BD-06)

The new order calculation at `backend/core/order/service.py:258-281` selects the
current state and stores the unused tax heads as zero (`:269`, `:274`). Completion
still reads the buyer's **current** state at `:687`. Thus the stored rate and the
destination used to finalize the document can cease to describe the same quote.

**Current-code proof:** same-state ₹100 order with 9% CGST, 9% SGST and 18% IGST
catalogue rates quotes ₹118. Change the buyer's state from `29` to `27` before
completion. The final invoice is **₹100 with all GST heads zero**. The opposite
direction has the same information-loss problem. The order must preserve the
agreed destination/tax facts or require an explicit valid requote.

The stable-destination calculation still uses separate raw float math. With the
usual round-off setting enabled, ₹100.50 at 18% quotes **₹118.59** but creates a
**₹119** final invoice. Use a shared deterministic quote/invoice calculator,
including per-line precision, discounts, destination and round-off policy.

### 4. P1 — financial summaries remain contradictory (BD-04)

The narrow `get_business_overview` full-return case now passes, but three distinct
boundaries remain:

- **Old surfaces remain active.**
  `backend/services/handlers/invoices.py:229` still sums all positive legacy
  amounts, and `backend/services/recommendations.py:191` still builds its live AI
  prompt snapshot from the same old sums. A fully returned **unpaid** ₹100 sale
  still produces **₹200 revenue and ₹100 collected** in the deterministic
  handler; the AI prompt says revenue ₹200 and collection rate 50%, while the new
  overview correctly says zero. Excluding credit notes only in one summary does
  not establish parity for the rest of the product.
- **New mixed-legacy regression.**
  `backend/core/billing/balances.py:56` chooses one tenant-wide branch: use all
  receipt rows if any exist, otherwise fall back to paid invoice projections.
  A legitimate legacy paid invoice of ₹100 plus a new paid invoice/receipt of
  ₹10 now reports **collected ₹10 rather than ₹110**. Legacy fallback must be
  evaluated per invoice, with clear receipt/advance semantics.
- **Overdue is still gross.**
  The aggregate at `backend/core/billing/balances.py:43` adds original totals for
  `status="Overdue"`; it does not use the linked-note/receipt balance service.
  A ₹100 invoice with ₹20 received and a ₹50 return reports **overdue ₹100** while
  `invoice_balance` correctly reports **₹30** outstanding.

Update every exposed deterministic handler, prompt snapshot, tool and reminder
selector; verify all of them against the same legacy/receipt/return fixture. The
single WP1 test covers the simplest full-return case, not those other contracts.

### 5. P2 — debit-note uniqueness is missing on existing deployments (BD-13)

The durable allocator at `backend/core/purchase/commands.py:466` is a good change.
The new partial unique index at `backend/database/models.py:623` is also correct
for a newly created table. However, startup's
`Base.metadata.create_all(...)` at `backend/database/migration.py:1624` does not
add newly declared indexes to an already existing `purchase_invoices` table. No
separate installer or Alembic revision for this index exists.

**Current-code proof:** simulate the predecessor index state, run `create_all`,
then call the current debit-note command twice for two source purchases with the
same explicit number. Both notes commit with **`DN-SAME`** for the same business.
The explicit number is also accepted by `CreateDebitNoteRequest` at
`backend/core/api/purchases.py:224`, so this is an exposed path, not just a direct
DB-write thought experiment.

Add an explicit upgrade migration with existing-duplicate diagnostics and a
controlled reconciliation procedure; install and verify the constraint on both
supported database types. A fresh in-memory monotonic sequence test does not
prove an existing merchant upgrade or PostgreSQL concurrency.

### 6. Open product scope — supplier payments and linked refunds (BD-11)

The new `test_bd11_supplier_payment_boundary` verifies a correct 422 refusal at
the customer receipt endpoint. That boundary was already present in the original
audit snapshot. It does not implement an append-only supplier-payment history,
partial vendor settlement, linked cash/bank customer refund or return-credit
allocation. Those workflows remain open, with unavailable actions requiring an
explicitly limited product scope until implemented.

## Test evidence and compatibility limits

Both pytest runs used the existing guarded runner, external-network blocking,
synthetic credentials, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` and distinct worker DB
names. A first sandboxed run was interrupted at the known Windows asyncio local
socketpair restriction before its API fixture could run. The completed runs used
the same guard outside that restriction. They did not contact merchant services.

1. Worker `remed_domain_api`: **271 passed in 37.10 seconds**.

   ```text
   test_wp1_financial_contracts.py test_wp3_authorization_lifecycle.py
   test_actions.py test_stock_ledger.py test_purchase_commit.py
   test_money_pure_functions.py test_money_audit_regressions.py
   test_wp4_wp5_operational.py
   ```

2. Worker `remed_domain_more`: **117 passed, 4 failed, 1 skipped in 28.58 seconds**.

   ```text
   test_reports_agree.py test_money_reconciliation.py test_trial_balance.py
   test_phase4.py test_phase4_sync.py test_phase3.py test_self_healing_engine.py
   test_hash_chain.py test_accounting.py test_invoice_sequence.py
   test_revenue_month.py
   ```

   All four failures arise at `backend/tests/test_phase4_sync.py:99-101`: the old
   helper jumps from `accepted` to `completed`, now correctly rejected by the new
   strict graph. The current frontend's `STATUS_FLOW` already uses
   accepted → packed → dispatched → completed. The new valid-progression proof
   succeeds and the original terminal mutation is blocked. Update those fixtures
   and rerun their bilateral posting, exactly-once and legacy-repair assertions;
   do not call the whole integration suite green or treat the stale helper as
   proof that terminal protection is defective.

3. `backend-proofs.py`: **20 explicit current-behavior checks, 10 expectations
   passed and 10 failed**; exact inputs/observations in
   `backend-proof-results.json`. The harness records every corrected-behavior
   expectation rather than asserting that old bugs persist. Exit 0 means the
   observations were recorded successfully, not that the financial package is
   fully correct. The original audit's old-bug reproduction was not used as a
   regression test.

The existing/new user tests can pass while the counterexamples fail because the
WP1 tests use fresh schemas, stable destinations, disabled round-off and positive
new cost snapshots. They do not cover old schema upgrades, legitimate zero costs,
mixed legacy receipts or all exposed AI read paths.

## Recommended next work

1. Fix historical-cost migration/unknown-cost handling and zero-cost return
   snapshots before deploying the new cost column; add upgrade-shaped tests.
2. Preserve/requote B2B tax destination facts and share quote/final rounding.
3. Complete the financial read-model migration, including per-invoice legacy
   fallback and actual remaining overdue, then assert cross-surface parity.
4. Install DN uniqueness through a real existing-schema migration, and verify
   the supported PostgreSQL upgrade/concurrency path.
5. Update the bilateral test helper to the intended graph and rerun its financial
   checks. Keep supplier/refund capabilities explicitly unavailable until the
   missing append-only workflows are implemented.
