# Money-sector agent audit — 29 October 2026

## Verdict and scope

The reviewed core is materially safer after the fixes below, but this audit does
**not** establish that every financial workflow is production complete. The open
advance-receipt, supplier-payment, historical COGS and actual cash-refund workflows
must be addressed or explicitly disabled before advertising full money-sector
coverage. Existing production-data discrepancies still require reconciliation.

This agent reviewed Billing source, command/API/view contracts, financial plans,
and isolated regression tests. Billing UI, registration/trial policy and Field Team
have separate agent reviews. No real merchant database, payment, refund, shift
closure or cloud business deletion was executed. All fixtures are synthetic.

## Sector inventory

| Sector / customer-facing surface | What was checked | Evidence and current boundary |
|---|---|---|
| POS / PS sales | Atomic invoice/header/lines/stock/journal composition; numbering, duplicate/retry wall, tax inclusive/exclusive, bill and cash discounts, paid/partial/credit | `test_billing.py`, `test_sales_api.py`, `test_cash_discount.py`, `test_pending_invoices.py`; source includes deterministic rounding and tenant/product locks. Multi-terminal live soak remains necessary |
| Checkout received/change/credit | `usePaymentFlow.js`, confirmation choice, partial tender/customer requirement, durable offline queue, committed-cart retirement | Existing frontend hook/modal tests are part of root's full Billing run. No physical cash/payment was taken during this audit |
| Printing | Saved receipt snapshot, persistent print job, explicit retry, HTML-not-PDF fallback handling and PDF abort/disposal | `test_print_and_einvoice_pure.py` plus frontend `usePaymentFlow` / invoice viewer tests. This proves contracts, not printer hardware or a deployed browser print dialog |
| Sales returns / credit notes | Original snapshot prices/taxes/discounts, cumulative return limits and paise allocation, cash-discount/round-off reversal, source warehouse/batch | Fixed; `test_money_audit_regressions.py` covers full and repeated partial returns, multiple products, cess, tax-inclusive pricing, duplicate rows and source warehouse/batch |
| Supplier bills / purchase confirm | Reviewed data normalization, finite values, header/line consistency, duplicate detection, conversion factors, stock-in and journal | `test_purchases.py`, `test_purchase_commit.py`, `test_purchase_status_vocabulary.py` |
| Purchase returns / debit notes | Source quantity limits, immutable line allocations, header discount/cess/round-off and original stock location | Fixed and covered by the new money regressions. Product-only returns remain blocked when the source contains multiple matching lines; source-line selection is required |
| Customer receipts | Finite positive money, tenant-bound invoice, row lock, idempotency, net invoice balance after credit notes | Fixed over-collection after returns; actual payment ledger takes precedence over a stale paid projection in read views |
| FIFO settlement / customer advance | Existing atomic settlement and mixed settlement+advance, return-adjusted dues, credit owed after paid returns | Linked-return balances fixed. Automatic settlement stops when unresolved return credit exists or the invoice is fully returned. Standalone prepayment without an invoice anchor remains an open blocker |
| Customer / vendor accounts | Party outstanding, invoice account, return credit, banked advance separation, list action eligibility | Shared `core/billing/balances.py` now supplies linked-note-adjusted balances. Return credit is exposed separately and does not pretend a cash refund happened |
| Supplier payments | Frontend “Made” option and `/payments` posting path | Confirmed unsupported: API previously used the customer receipt command regardless of type. API now rejects non-received types; UI agent disabled the advertised supplier action. A real supplier-payment command is still needed |
| Expenses / cashbook | Finite positive amount, append-only records, locked periods, journal write in same transaction | Added finite schema guards; existing expense-delete prohibition and journal tests remain intact |
| Shifts / drawer | Opening count, paid in/out, close cash/UPI, carry-forward/removal, concurrent close versus money write | Added finite guards and locking on command/open-shift stamping paths; `test_shifts.py`, `test_shift_service_unit.py` passed after keeping established error phrases |
| Stock / valuation | Append-only ledger, fractional stock, inventory projection, negative-stock policy, warehouse/batch attribution | Fixed the new-cache branch that rounded fractional stock to an integer; finite stock deltas and invalid existing balances now fail closed. Historical sale COGS still uses mutable catalogue cost |
| Accounting / P&L / journal | Balanced append-only entries, period lock, hash chain, returns, GST and discount reconciliation | Fixed P&L journal metrics to net debit/credit reversals and reverse Discount Allowed with cash-discount returns. Full return regression verifies all account balances return to zero |
| GST / reports | Existing report/print contracts, source tax snapshots and return reversal rather than recomputing present-day prices | Cess/tax snapshot refund cases tested. This is software verification, not a legal certification or live e-invoice-provider filing |
| B2B money / sync | Tenant-scoped billing primitives and source financial invariants | Root's B2B import/sync review owns its transfer changes and PostgreSQL tests. Field agent is aligning Field read/collection projections to the same linked-note balance contract |

## Confirmed defects fixed in this review

1. **P1 — over-refund on discounted or MRP-inclusive sales.** The old credit-note
   command multiplied returned quantity by the gross unit price, then added tax
   again. It ignored the original line/bill discount and tax-inclusive taxable
   snapshot. The command now allocates original taxable/discount/GST/cess snapshots
   cumulatively, subtracting actual prior credited components. The final partial
   return consumes the remaining paise exactly.
2. **P1 — purchase return larger than the received bill.** Header discount, cess
   and round-off were omitted from debit notes. They now allocate cumulatively
   against the immutable source bill. Full partial-return sequences reconcile to
   the original grand total.
3. **P1 — repeated return rows and return races.** Each duplicate product request
   previously checked the same pre-return quantity independently. Both commands
   now reject duplicate requested product IDs, lock the source document and refuse
   a return-of-a-return. Ambiguous original repeated product rows fail closed
   instead of choosing an arbitrary batch/price.
4. **P1 — returned goods still collectible.** Customer/vendor statistics, FIFO and
   receipt guards previously ignored linked credit notes or added debit notes with
   a positive sign. A shared projection now reduces source obligations by linked
   notes. A fully returned unpaid sale has zero due and rejects a further receipt;
   a partial return plus receipt has the same remaining balance in commands and
   views. Previously paid returns expose credit owed without inventing cash payout.
5. **P1 — nonfinite financial inputs.** Positive comparisons alone did not reject
   NaN/Infinity in receipt, settlement, expense, return and shift paths. API and
   command guards now reject them; journal posting also refuses nonfinite amounts.
   Billing has a safe validation error handler that excludes raw inputs/contexts,
   so raw numeric `1e309`, `Infinity` and `NaN` return JSON 422 rather than a JSON
   serialization 500 or echoed private input.
6. **P1 — supplier-payment label posted a customer receipt.** `/payments` accepted
   `type='made'` while always executing the sales-receipt command. It now fails
   closed with explicit guidance. A payment-out workflow is not fabricated.
7. **P1 — P&L overstated after returns.** The journal section read Sales/GST credits
   and Discount Allowed debits without subtracting reversals. Metrics now use net
   movements, and invoice/journal reconciliation includes the cash-discount effect.
8. **P2 — fractional stock and wrong return location.** New inventory cache rows
   rounded fractional stock to an integer, while existing-row updates used floats.
   New rows now preserve the ledger quantity. Returns preserve original godown,
   batch and expiry, along with invoice identity snapshots.
9. **P2 — drawer-close race exposure.** Money commands now lock the open shift when
   requiring/stamping it; close and drawer movement commands use the same lock.
   Input failures preserve established public error phrases while adding finite
   validation.

The source-total fallback remains compatible with legacy CSV data:
`total_amount or amount or 0`. Modern genuinely free bills store zero in both
columns. Return adjustments apply only after that gross source total is resolved.

## Open release decisions and recommendations

| Priority | Concrete gap / evidence | Recommendation |
|---|---|---|
| P1 | `core/billing/commands.py::settle_customer_dues` banks a standalone prepayment in `Customer.credit_balance` when there is no `last_pay_id`. No journal is posted, and a repeated body idempotency key has no receipt anchor to find. A request header replay key can cover one route invocation, but cannot replace a durable advance receipt | Add an append-only customer advance receipt with stable UID/idempotency, payment method/date/operator/shift, Dr Cash/Bank and Cr Customer Advances; releasing it against an invoice must not take cash again. Until then disable standalone prepayment entry. Mixed invoice settlement+advance already has a receipt/journal anchor |
| P1 | Supplier payments have no purchase-payment ledger/command. Purchase Paid status is a coarse full-payment indicator; partial supplier settlements cannot be represented reliably | Implement append-only purchase payments with purchase/vendor allocation, journal Dr AP / Cr Cash/Bank, returns, idempotency and shift treatment. Keep the disabled UI truthful until this exists |
| P1 | `core/api/reports.py::report_pnl` calculates COGS with current `Product.cost_price` | Persist sale-time cost/valuation snapshots on invoice lines (and matching return reversals), migrate only where historical evidence exists, and test that changing today's catalogue cost cannot change yesterday's profit. Do not guess/backfill old cost from today's price |
| P1 | Credit notes currently establish a customer credit/refund obligation; they do not execute or record a real cash/bank refund. Drawer paid-out categories do not provide a linked customer-refund command | Add an explicit append-only refund linked to the credit note, with method/amount/shift, idempotency and Dr refund/AR credit / Cr Cash/Bank accounting. Keep “return posted” separate from “money refunded”; do not use an owner-withdrawal or expense label to hide a refund |
| P2 | Return requests identify a product, not the exact original line UID. An original invoice can legitimately contain the same product with different batches/serials/prices | Add source-line UID to both sales/purchase return models and UI, then safely support per-line cumulative limits. The current guard deliberately blocks ambiguous product-only returns |
| P2 | Purchase debit-note auto numbering uses `COUNT + 1`, unlike the monotonic sales/CN allocator | Give debit notes their own business-scoped durable sequence and database uniqueness, with two-source-invoice concurrent generation tests |
| P2 | Legacy credit notes without a valid `parent_invoice_id`, corrupted totals or previous over-refunds cannot be safely inferred from arbitrary free-text notes | Reconcile/link them against evidence before enabling further collection/returns. Shared monetary projections count verified same-business parent links; they do not guess from a substring |
| Operational | Existing supplied logs report historical overpaid receipts, duplicate open shifts and overfilled documents | Reconcile the correct backup against receipts and counted cash. These code fixes do not repair those historical records and do not prove that online production is already clean |

Cross-invoice use or payout of a customer's return credit requires an explicit
allocation/refund record. The account view exposes credit separately; automatic
FIFO does not silently take more cash while that credit is unresolved. No new
supplier-payment, standalone-advance, COGS snapshot or cash-refund model was rushed
into this change set.

## Verification and practical limits

Coordinated Billing SQLite access avoided concurrent destructive test fixtures.
The full broad sector command covered:

```
tests/test_money_audit_regressions.py tests/test_billing.py
tests/test_sales_api.py tests/test_cash_discount.py tests/test_pending_invoices.py
tests/test_invoice_account.py tests/test_purchases.py tests/test_purchase_commit.py
tests/test_purchase_status_vocabulary.py tests/test_stock_ledger.py
tests/test_negative_stock_policy.py tests/test_accounting.py tests/test_journal.py
tests/test_audit_journal.py tests/test_shifts.py tests/test_shift_service_unit.py
tests/test_print_and_einvoice_pure.py tests/test_phase1b.py
```

- Broad sector run: **267 passed**, after correcting validation-message regressions.
  That run preceded the later shared return-balance projection.
- Final balance/receipt/FIFO/shift/purchase/stock run: **169 passed**, including
  `test_settle_dues.py` and `test_settle_fixes.py`.
- Final header-query/legacy-total/free-sale projection subset: **5 passed**,
  31 deselected. This checks the last read-performance/legacy-total refinement.
- The full focused money file passed **36 / 36 on real disposable PostgreSQL**
  (21.40 seconds), including final return-balance/legacy queries and raw nonfinite
  JSON rejection. An earlier PostgreSQL attempt had 32 passes and four
  fixture setup errors because explicit suite users left the serial counter
  behind; the fixture now chooses a free synthetic owner ID. No financial command
  failed in that setup error.

Tests use guarded disposable databases; external calls are blocked. Root owns the
overall frontend count/build evidence and integrated sync/registration smoke.
Neither a source review nor these passing suites proves physical printer behavior,
two-terminal races under real deployment load, deployed backup/restore recovery,
tax-provider acceptance, all historical data correctness or the completion of the
open workflows above.
