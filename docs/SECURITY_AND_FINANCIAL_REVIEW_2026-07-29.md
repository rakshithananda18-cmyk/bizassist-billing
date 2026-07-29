# Security, Tenant Isolation, and Financial Integrity Follow-up — 2026-07-29

This is the dated follow-up to
[`SECURITY_AND_FINANCIAL_REVIEW_2026-07-28.md`](SECURITY_AND_FINANCIAL_REVIEW_2026-07-28.md).
It records the P0 remediation and validation completed on 29 July without
overwriting the original audit evidence.

## Release position

**Not approved for public cloud release yet.** The source paths below are
fail-closed, but release still depends on backend tests in a repaired runtime,
PostgreSQL/RLS verification with the real cloud role, and staged local/cloud
reconciliation checks.

## Findings fixed in this follow-up

| Area | Finding | Remediation |
|---|---|---|
| Legacy B2B Purchase Bills | Completed historical B2B orders with a supplier invoice but no linked buyer stock receipt could not create the missing buyer payable. The UI also inferred stock receipt from the seller invoice. | The buyer-owner reconciliation action now creates the missing Purchase Bill and journal only; it never creates stock. The UI exposes `buyer_stock_received` only from a buyer-owned ledger proof and flags unproven historical stock for review. |
| New B2B completion | Seller sale, buyer receipt, and buyer payable could previously become separate partial effects. | Completion now writes seller sale/receivable, buyer stock receipt, buyer Purchase Bill/payable, and journals within one transaction. The buyer bill uses a deterministic shared-order UID; counterparty raw document IDs are not exposed. |
| Manual stock adjustment | A product adjustment wrote through the ledger and then incremented the inventory cache again. Batch/expiry were also omitted from the ledger movement. | The append-only ledger is the sole quantity writer. The cache is a projection, batch/expiry are retained, and non-2xx UI responses never appear as a saved adjustment. |
| Fractional stock | Inventory cache used integer stock and rounded ledger balances, corrupting weight/length/volume valuation. | Fresh models use floating stock; cache refresh/rebuild retains fractions; SQLite is compatible and the PostgreSQL migration upgrades `inventory.stock` to `DOUBLE PRECISION`. |
| Normal Purchase Bill confirmation | Removing an OCR item left stale header totals. The API could accept an empty bill, zero quantity, non-finite numbers, or values that let the Purchase Bill/journal disagree with stock lines. | Browser draft totals now recalculate after edit/remove. The server validates all line inputs before writing, derives persisted monetary line/header values from quantity/rate/GST, requires a positive reconciled total, and rejects conflicting non-zero client headers. The UI displays the server’s specific validation error. |

## Tenant-isolation position

- A shared BizID is the cross-database business identity. Local and cloud
  numeric user/business IDs are intentionally not treated as portable IDs.
- B2B/sync code resolves the BizID in the current database and scopes all
  buyer/seller documents by their local business owner.
- Buyer responses never receive seller-local invoice IDs, and child mutations
  prove ownership through their tenant-scoped parent.
- The browser offline queue remains partitioned by BizID and user ID; a logout
  detaches the active scope rather than replaying another user’s operations.

## Validation completed

- Modified backend sources and regression tests passed Python syntax
  compilation with the available bundled runtime.
- Billing frontend production build passed.
- Billing frontend regression suite passed: **50 files, 349 tests**.
- Targeted B2B Orders UI suite passed: **13 tests**.
- Working-tree whitespace check passed.

## Required before release

1. Recreate/repair `venv` using the supported Python 3.9 runtime, then run
   `./run_tests.bat fast` (or its PowerShell equivalent) and retain the output.
   The checked-in virtual environment currently points to a deleted Python 3.9
   executable, so backend pytest could not run in this workspace.
2. Test Purchase Bill success/failure atomically on a disposable database:
   create/edit/remove/retry, then verify one Purchase Bill, exact stock-ledger
   movements, and one balanced journal; confirm invalid drafts leave no rows.
3. Test the existing historical B2B order only after the updated backend is
   actually running. Its repair action must create the payable bill only and
   must not change buyer stock.
4. Deploy the same backend revision to the cloud before using the B2B repair
   path through a cloud/proxy session. A local source change does not update a
   separate cloud service.
5. Run production-role PostgreSQL/RLS and two-tenant direct API tests, then
   complete local/cloud offline, retry, conflict, backup, and restore drills.

## Operational caution

Do not globally rebuild historical inventory cache rows until batch history is
audited. Some older rows may have batch labels only in the cache, while their
ledger entries were unbatched. Totals are reconstructable, but batch allocation
needs owner-reviewed reconciliation rather than an automatic rewrite.

## Conclusion

The changed paths now reject invalid monetary and stock data rather than
silently accepting it. That is a significant hardening step, not a claim of
absolute certainty: full confidence comes only after the required backend,
database-role, packaged-runtime, and operational recovery verification passes.
