# Backend domain audit — 30 October 2026

Repository snapshot: `f90ea1f` at start of review. This is a code and disposable-data
audit, not a claim that deployed merchant data or every live workflow is correct.
No production code was changed, no merchant database was repaired, and no payment,
message, deployment or external network request was performed.

## Main conclusion

The most important missing piece in this area is **one financial contract across
every write path and every read surface**. The POS command layer contains serious
guardrails, but legacy AI actions bypass it, AI tools still add gross legacy
invoice amounts, and stock cache aggregation disagrees with the stock ledger.
More visible features will compound these inconsistencies until those boundaries
are enforced and tested together.

The earlier plan's principles remain suitable: money is deterministic, every money
change is one atomic command, the stock ledger is authoritative, AI advises, and
the network shares only the permitted slice. Several current paths violate those
principles. The findings below distinguish newly demonstrated defects from gaps
already acknowledged in the 29 October money audit.

## Coverage and confidence

- The companion CSV inventories all **496 tracked `backend/` files** at the
  snapshot: **400 text files statically screened**, including **379 Python files
  successfully AST parsed**; **29 files received manual targeted source/contract
  tracing** and **9 test files received manual assertion/fixture review**.
- The remaining **96 inventory entries** are explicitly excluded here because
  they belong to the trust/sync/ops agent or are generated/data artifacts. They
  are not silently counted as reviewed application code.
- `screened` means automated full-text and structural inspection. It does not
  mean every branch was manually understood or executed. `deep` means targeted
  manual traces of the relevant contracts and invariants, not a clean bill of
  health for an entire file.
- The highest risk paths were traced through models, API exposure, command
  composition and the prior audit. Ten current behaviors were reproduced using
  **real implementation functions and real ORM models in in-memory SQLite**.
- PostgreSQL concurrency, deployment configuration, historical data, physical
  printers and cloud/local interaction are outside this domain pass's execution
  evidence. The other agents own their respective review findings.

## Actionable issue register

### BD-01 — P1: AI “mark paid” changes status without receiving or posting money

**Evidence:** `backend/services/actions.py:276`, particularly `:294-300`;
registered at `:684-687`; exposed through owner/manager-confirmed
`backend/routes/actions.py:61`.

The action directly assigns `r.status = "Paid"`, adds `ActionLog` and commits. It
does not call `record_payment`, create `InvoicePayment`, change `paid_amount`, post
a journal, validate the remaining amount after returns, or enforce a closed
accounting period. Preview/confirmation protects intent but does not supply those
financial effects. The same invoice can be shown as paid to legacy AI and still
collectible to the newer balance projection.

**Reproduced:** a ₹100 unpaid invoice becomes `status="Paid"` with `paid_amount=0`,
zero receipts and zero new journals. The action reports success.

**Fix:** route the action through the same receipt command and balance service as
the billing flow, including payment method/date, operator/shift, idempotency and
period lock. Disable this action until it can perform that complete contract.

### BD-02 — P1: default warehouse/unbatched movements duplicate stock in the cache

**Evidence:** `backend/core/stock/ledger.py:76-79`, `:116-142`, `:163-172` and
`:215-219`.

`current_stock(..., godown_id=None, batch_no=None)` treats `None` as “all buckets”.
`record_movement` uses that aggregate as the balance for a movement in a particular
NULL warehouse/batch bucket. `_refresh_inventory_cache` then writes it into that
exact NULL bucket. Other buckets remain present. Rebuilding the cache uses the
same ambiguous query and does not reliably repair the inconsistency.

**Reproduced:** B1=5 and B2=7; sell 1 without a batch. Ledger total is 11, but
inventory rows become B1=5, B2=7, NULL=11, summing to **23**. This affects stock
displays and inventory valuation even while the append-only ledger is correct.

**Fix:** distinguish an omitted aggregate filter from an explicit NULL bucket,
for example with a sentinel or separate aggregate/bucket APIs. Every projection
write must use exact warehouse/batch predicates. Reconcile existing caches from
the corrected bucket query, with a report before applying repairs.

### BD-03 — P1: purchase-unit cost is stored as stock-unit cost

**Evidence:** `backend/core/purchase/commands.py:288`, `:300`, `:335-348` and
`:388-399`; valuation consumes `Inventory.stock * Inventory.cost_price` in
`backend/core/api/reports.py:1414` and `:1631`.

The purchase line amount uses purchase quantity × purchase unit price. Stock
receipt multiplies that quantity by `conversion_factor`, but product/inventory
cost is assigned the unchanged purchase unit price. A carton price therefore
becomes the per-piece cost. The default selling-price markup is also derived
from the purchase-unit price.

**Reproduced:** one carton containing 12 pieces costs ₹120. The bill is ₹120 and
stock increases by 12 pieces, each cached at cost ₹120: inventory value **₹1,440**.

**Fix:** define and store purchase-unit price and base-stock-unit cost separately.
Normalize cost by conversion factor, including landed-cost allocation where
applicable, and use the base-unit value for stock valuation/COGS. Do not silently
rewrite historical costs from today's catalogue.

### BD-04 — P1: AI metrics treat a return as revenue and cash collected

**Evidence:** `backend/services/tools/business.py:15-17`,
`backend/services/tools/invoices.py:15-21`,
`backend/services/handlers/dashboard.py:27-30`, and
`backend/services/recommendations.py:50-52`.

Several AI-facing paths sum `Invoice.amount` without a credit-note sign and infer
cash collected from `status="Paid"`. New credit notes intentionally store a
positive document amount and are immediately marked Paid. Partial receipts and
linked return balances are also not represented by those legacy aggregates.
Grounding the model on these tools still supplies incorrect business facts.

**Reproduced:** create an unpaid ₹100 sale, then return it completely. Actual net
revenue added is zero and no cash is received. `get_business_overview` increases
`total_revenue` by **₹200** and `collected_revenue` by **₹100**.

**Fix:** provide shared revenue/receipt/outstanding read models for the POS,
reports, AI tools, deterministic handlers, reminders, charts and recommendation
signals. Explicitly distinguish gross invoices, sales returns, net revenue,
actual receipts, advances, outstanding and refund obligations. Add parity tests
that exercise these surfaces with the same partial-payment/return dataset.

### BD-05 — P1: automatic re-sealing makes altered contents pass the integrity check

**Evidence:** `backend/services/self_healing.py:40-83`, especially `:68-77`;
called unconditionally at `:389`; reachable at
`backend/core/api/reports.py:1509-1520`.

For any hash mismatch, the repair recomputes the chain from the journal's current
contents and overwrites `prev_hash`/`entry_hash`. It does not distinguish a
replication-order problem from changed financial content and does not preserve
the mismatch as a distinct, evidence-backed recovery decision or compare the
contents to a trusted checkpoint. Generic ORM `TableAlteration` auditing can
retain old/new hash values and earlier application writes, which is useful
evidence; the repair neither validates those records as the original truth nor
uses them to decide whether the current content is trustworthy.

**Reproduced:** alter an already posted journal's narration. `verify_chain`
reports `ok=false`; `heal_hash_chain` changes its stored hash; `verify_chain` then
reports `ok=true` for the altered entry. This demonstrates loss of the primary
integrity alarm, not that every possible historical copy or generic audit row has
been erased. The same hash function covers the financial lines.

**Fix:** make diagnosis read-only for content mismatches. Preserve immutable
mismatch evidence and the previously trusted checkpoint; require a justified,
explicit reconciliation procedure. A corrected financial fact should be a
reversal/reposting or a separately recorded recovery event, not an unexplained
replacement of its integrity proof. Scope safe ordering repair separately.

### BD-06 — P1: B2B order and final invoice calculate different GST totals

**Evidence:** `backend/core/order/service.py:253-280` and `:645-655`;
`backend/core/billing/commands.py:71-80` and `:151-167`.

Order creation adds CGST, SGST and IGST together. The final sale correctly chooses
the intra/inter-state heads. Product records can legitimately carry both sets of
rates, so the buyer confirms one order amount and receives a different final
invoice even without any price/quantity change.

**Reproduced:** same-state buyer/seller; ₹100 item with CGST=9, SGST=9, IGST=18.
Order total is **₹136**; completed seller invoice is **₹118**.

**Fix:** reuse the deterministic pricing/tax calculation for the order quote and
the final invoice. Capture the destination/tax-inclusive policy and resolve
rounding consistently. If changes require a requote, represent and confirm it
explicitly rather than silently changing the amount.

### BD-07 — P1: direct ordering bypasses a connection's catalogue-category policy

**Evidence:** `backend/core/order/service.py:92-93` filters the browsable catalogue,
but `:230-234` checks only product ID, seller ownership and active status during
`create_order`. The category restriction is absent there.

**Reproduced:** an accepted connection allows only “Visible category”. A product
in “Hidden category” is absent from the catalogue, but ordering its integer ID
succeeds and exposes its product name and tiered unit price in the order.

**Fix:** enforce the connection's permitted catalogue predicate in the order
command as well as the catalogue serializer. Share that predicate so listing and
ordering cannot drift. Add a negative isolation/policy test using a hidden ID.

### BD-08 — P2: completed B2B orders can be rejected without financial reversal

**Evidence:** `backend/core/order/service.py:318-343`.

Seller transitions validate only membership in the list of status names and
disallow the word `cancelled`; they do not validate the current-to-next edge.
Terminal orders can be reopened or rejected. Existing financial documents and
stock effects remain.

**Reproduced:** pending → completed → rejected succeeds. The final order is
`rejected` while `seller_invoice_id` remains populated and the sale/purchase/stock
effects still exist.

**Fix:** implement a transition table with terminal states. Define separately the
credit/debit-note process for an already fulfilled order. Test every disallowed
edge on the backend, including a client bypassing the displayed buttons.

### BD-09 — P1, previously acknowledged: standalone advances are neither durable receipts nor idempotent

**Evidence:** `backend/core/billing/commands.py:874-908`, `:975-988`;
body key accepted at `backend/core/api/parties.py:336` and passed at `:375`.

The retry lookup depends on per-invoice receipt rows. With no outstanding invoice,
there is no `last_pay_id`; the command increments `Customer.credit_balance` but
writes no receipt or advance journal. Replaying the same body key adds it again.
A route header replay guard can cover one specific request, but does not turn
this body-key money command into a durable advance workflow.

**Reproduced:** submit a ₹100 standalone advance twice with the same key. Customer
credit becomes **₹200**, with **zero receipt rows and zero journal entries**.

**Fix:** an append-only advance receipt with UID, unique request key, method,
date/operator/shift and Dr Cash/Bank / Cr Customer Advances. Application to a sale
must release the liability without receiving the cash a second time. Disable
standalone advance entry until this exists.

### BD-10 — P1, previously acknowledged: historical profit uses today's cost

**Evidence:** `backend/core/api/reports.py:264-280`; `InvoiceLineItem` has no
sale-time cost snapshot in `backend/database/models.py:347-402`.

COGS joins sale quantities to current `Product.cost_price`. Receiving a later
purchase or editing the catalogue changes earlier reported profit and prior
return reversals. This is distinct from the conversion bug in BD-03.

**Fix:** immutable sale-time valuation/cost snapshots with consistent return
reversal, explicit valuation policy and evidence-based historical migration.
Acceptance test: changing today's cost cannot change a closed prior period's P&L.

### BD-11 — P1 workflow gap, previously acknowledged: supplier payments and actual customer refunds remain incomplete

**Evidence:** `backend/core/api/payments.py:291-295` explicitly rejects supplier
payments; `backend/core/accounting/posting.py:307-320` has only a coarse full-paid
purchase posting decision; `backend/core/billing/balances.py:1-5` explicitly
distinguishes a credit note from a cash refund.

These are missing workflows rather than a claim that the currently rejecting API
silently posts supplier payments. A purchase bill and a customer return do not
cover partial supplier settlement, supplier payment history, linked cash/bank
refunds or allocation of customer return credit across invoices.

**Fix:** separate append-only supplier payments and customer refunds/allocations,
with source links, idempotency, journals and shift treatment. Keep unavailable
actions visibly disabled. Treat these as release boundaries when describing
accounting coverage to a pilot merchant.

### BD-12 — P2: supplier catalogue shows one inventory bucket rather than total stock

**Evidence:** `backend/core/order/service.py:125-150`.

The batched inventory query is an improvement over N+1 reads, but
`stock_by_product[pid] = qty` overwrites each earlier warehouse/batch row. The
visible exact stock or stock band depends on whichever row is returned last.
This is separate from the NULL-bucket inflation in BD-02.

**Reproduced independently of BD-02:** a clean product has two valid batch rows
with quantities 5 and 7; both cache and ledger total 12. Catalogue stock is **7**.
The overwrite is explicit in source; SQL row ordering can change the displayed
bucket without a business-level stock change.

**Fix:** aggregate allowed stock buckets with `SUM/GROUP BY` or derive the product
quantity from a corrected authoritative projection. Decide consistently whether
the network exposes all godowns, sellable stock or available stock after holds.

### BD-13 — P2, previously acknowledged: purchase debit-note numbering uses count + 1

**Evidence:** `backend/core/purchase/commands.py:434-438`;
`backend/database/models.py:619-622` has no business/debit-note-number uniqueness.

Different source purchases lock different rows, so concurrent debit notes for the
same business can both count N and allocate `DN-(N+1)`. The sales/CN sequence has
already solved this class of problem; debit notes do not use it.

**Fix:** a business-scoped durable debit-note series and database uniqueness,
including concurrently returning two different original purchase bills. Reconcile
existing duplicate numbers before installing the constraint.

## Previously planned direction and current gaps

| Intended principle | Current evidence | Consequence for the next plan |
|---|---|---|
| `FOUNDATION.md` §2.2–2.4: append-only money, one atomic command, AI never decides money | BD-01 bypasses the financial command; BD-04 supplies incorrect deterministic inputs to advice | Unify writes/reads before expanding autonomous actions |
| D4: stock ledger is truth; inventory is a rebuildable cache | BD-02 reproduces aggregate/bucket drift; BD-03 creates unit-cost valuation drift | Fix bucket semantics and unit economics, then perform controlled cache reconciliation |
| Sharing policy is the only cross-business slice | BD-07 orders outside the allowed catalogue | Share authorization predicates across query and command |
| Tamper evidence and recovery preserve trust | BD-05 re-seals current content and clears the primary integrity alarm | Add evidence-preserving recovery, trusted checkpoints and diagnosis before repair |
| Completed phases require named behavioral tests | The selected existing tests pass, yet the ten demonstrated cross-surface cases were not covered | Add invariant tests spanning POS, AI, reports, returns, B2B and repair |
| Ship each phase sellable by itself; don't over-scope | The 29 October report still lists advances, supplier payments, COGS snapshots and real refunds as open | Explicit pilot scope and truthful availability are prerequisites to claiming complete accounts |

`backend/FOUNDATION.md` still calls purchase/connections future phases and ends its
foundation status with sales-counter UI as “Next”, despite those implementations
being present. `docs/MASTER_PLAN.md` is more recently reconciled. Use the latter's
dated evidence and the detailed current findings, rather than treating every old
unchecked item as a fresh defect or every old green marker as current validation.

## Recommended execution plan for this domain

1. **Contain incorrect money/stock behavior.** Disable the legacy mark-paid action
   and standalone advances; stop unconditional re-sealing; fix exact stock bucket
   queries and purchase-to-base-unit cost conversion. Capture affected records
   before any corrective script is approved or applied.
2. **Close network correctness gaps.** Enforce catalogue policy in create-order,
   share deterministic order/invoice tax calculation, add the transition graph,
   aggregate catalogue stock and allocate debit-note numbers durably.
3. **Unify financial projections.** Make receipts, signed sale/return totals and
   linked-note balances available through common services used by all AI tools,
   reminder selectors, charts, reports and UI summaries. Run one synthetic
   multi-period ledger dataset through every surface and assert parity.
4. **Finish the essential money workflows.** Advance receipts, supplier payments,
   customer refunds/credit allocation and immutable valuation snapshots should
   each ship as a bounded command/schema/UI/test slice. Historical reconciliation
   needs evidence and a dry-run report, not guessed automatic backfills.
5. **Prove the pilot on the actual supported deployment shapes.** Run disposable
   PostgreSQL plus SQLite workflow/race tests, followed by a rehearsed merchant
   journey including sale, partial payment, return, refund, supplier settlement,
   shift close, restore and offline replay. Preserve measured results with the
   commit and environment. Root's report coordinates cross-agent launch gates.

## Verification record

Commands below used the existing guarded runner, synthetic credentials, external
network blocking and worker-specific SQLite database names. No real database URL
was inherited. The reproduction uses an in-memory database and blocks all socket
connections and DNS.

```powershell
$env:PYTEST_XDIST_WORKER='audit_domain_pure'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
scratch/core-workflow-venv/Scripts/python.exe scratch/core_workflow_runner.py -q `
  tests/test_money_pure_functions.py tests/test_print_and_einvoice_pure.py `
  tests/test_dates.py tests/test_shift_service_unit.py
```

**328 passed in 16.72 seconds.** These are pure/helper/unit assertions, not proof
of the HTTP workflows or the deployed database.

```powershell
scratch/core-workflow-venv/Scripts/python.exe `
  docs/audit/2026-10-30/backend-domain-repro.py
```

**Exit 0; all ten defect reproductions confirmed.** Structured observations are
in `backend-domain-repro-results.json`. This script asserts current bad behavior
to make findings reproducible; it must become a proper regression test asserting
the corrected behavior when each issue is fixed.

Two mixed money/API runs emitted 24 progress dots and then stopped progressing;
both were interrupted without a final pytest summary. The second used plugin
autoload disabled and a 45-second faulthandler dump: it was blocked creating the
Windows asyncio event loop's local socketpair, before the HTTP signup handler
ran. Root identified the same sandbox restriction in Field tests and owns the
guarded rerun outside that restriction. This is an execution-environment limit,
not evidence of a signup application deadlock. Neither interrupted attempt is
counted as a green suite. The initial `venv` points to a removed Python
3.9 runtime; `.migration-venv` works but lacks application dependencies. The
pre-existing `scratch/core-workflow-venv` provides Python 3.12.14 and the usable
dependencies for the verification above.

The global pytest result dashboard is written by `backend/tests/conftest.py` and
can be overwritten by concurrent agent suites; this dated record and the actual
command output, not that shared JSON alone, establish this pass's results.
