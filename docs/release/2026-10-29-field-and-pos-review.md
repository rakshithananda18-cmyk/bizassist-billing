# Billing, Field Team and POS review — 2026-10-29

Follow-up: [cloud readiness continuation](2026-10-29-cloud-readiness.md) records
the subsequent public cloud checks, tenant-transaction fix and full real-PostgreSQL
Billing-schema validation, plus the framework caching change.

## Intended topology

Normal local development keeps two separate databases. Operational Field Team is **online and Pro-only**, using the **same cloud PostgreSQL database** and owner identity as online Billing. Local Billing changes become available there after Local + Cloud sync. Field Team does not operate from the local books. No real local database, deployed connection string, cloud secret or business record was changed during this review.

`dev/dev_env.ps1` no longer silently copies/repoints the normal Field Team development database to Billing. Explicit field-test mode still uses one disposable test database; its local URL and SQLite overrides are development-only. Deployed Field Team refuses SQLite and cannot disable the Pro gate. Existing paid-plan grace rules remain intact.

## Confirmed issues fixed

### Business and data alignment

- A failed/missing handoff no longer restores the previous Field Team business. Both the outgoing and returned workspaces check the expected BizID, and delayed old-session responses cannot overwrite/sign out the new session.
- Normal Billing navigation opens the cloud Field Team even when a stale local development URL is configured. A Billing client already using its cloud backend obtains the handoff from that active account, not an older sync token.
- Staff tenant context is bound before querying RLS-protected staff rows. Ordinary owner/staff requests also verify their signed BizID against the current owner, preserving the shared-cloud-ID requirement.
- Linked shop names, phone numbers and addresses now come from the current tenant-scoped Billing customer. Field-specific location, route, contact person and notes remain editable. Missing or invalid links are explicit rather than silently substituting another customer.
- Planned invoice snapshots remain historical. Task views expose current Billing totals and balances, staff completion refreshes/rechecks them, and missing/cancelled/cross-tenant invoices cannot fall back to old collection amounts.
- A completed partial collection can be planned again only after the reported money has been confirmed. Billing partial approvals can continue on the same invoice, with a confirmed-total checkpoint, transaction locking and atomic receipt/journal writes. Stale approval retries cannot book the same amount again.
- Desktop Billing shows a guarded online Billing link for field-collection approval; it does not post cloud receipts into a second local database. Owners can still book already-collected money after a Pro plan ends.

### Consistent workspace experience

- Owner workspace links, canonical business identity, hover-to-read names, shared component tokens and clear cloud/Pro copy align the apps.
- A scoped opener/origin/launch/BizID handshake carries both light and dark palette tokens, including custom colours. It sends no authentication token or profile data. Unknown CSS properties and unsafe colour values are rejected. Palettes are scoped by business on the receiving device.
- Field Team Settings links business profile/customers/appearance back to Billing. Both Billing entry points use the same owner, Pro and cloud-source checks.
- Sidebar sub-page foreground/background tokens are contrast-adjusted independently of the filled main-page selection. Both hover and keyboard focus use consistent styling.
- Field settings cards no longer shrink and clip their headings in the scroll container; page titles have heading semantics.

### Latest Billing/POS changes

- Imported the new checkout success sound and isolated optional sound/print/UI failures from invoice persistence. An acknowledged sale cannot be placed into the offline outbox as another save.
- Save locks survive slow requests and remain held while receipt/reset work is pending. Ambiguous server failures retain their idempotency key; validation failures permit a corrected new intent.
- Custom items without catalogue IDs now have an editable rate; zero-price lines are allowed, while invalid quantities/prices are rejected.
- Supplier statements use the API's `vendor` parameter. Customer advances and supplier balances cannot request a customer UPI payment; actions wait for a current successful ledger response. Stale responses and IST month boundaries are handled correctly.
- Dashboard charts are connected to their data and respect Privacy Mode. Chart totals use current invoice totals, remaining partial dues, tenant scoping, cancellations and credit notes instead of legacy status/amount guesses. Unavailable charts are not presented as zero activity.
- Report presets use IST business calendar boundaries, avoiding the previous-day error from serializing local midnight. Report printing restores page overflow and uses separate receipt page rules instead of a global thermal-paper rule.

## Verification

All checks below passed. Test artifacts and fixture databases remain in ignored `scratch/`; the two real local databases were not used as test fixtures.

| Check | Result |
| --- | --- |
| Billing full Vitest suite | 92 files, 735 tests passed |
| Field Team full Vitest suite | 12 files, 58 tests passed |
| Billing backend financial/API/print/sync selection | 149 tests passed |
| Latest Billing field-approval and dashboard regressions | 20 tests passed; overlaps the broader selection |
| Field Team full isolated backend suite | 125 passed; four external Billing contract cases intentionally skipped here and run separately below |
| Field Team against Billing's complete disposable schema | All four cross-app contract tests passed |
| Billing production build | Passed; main bundle 668.68 kB / 188.63 kB gzip; existing 500 kB chunk warning remains |
| Field Team production build | Passed; main bundle 456.54 kB / 134.96 kB gzip |
| Repository/script checks | Git whitespace check and PowerShell parsing of development/deployment scripts passed |

The financial selection covers dashboard totals, field approvals/rollback/idempotency, billing/sales API, print payloads and sync parity. Frontend regressions include slow/delayed POS saves, acknowledged-save failures, custom item rates, statement actions, auth switching, stale responses, bridge validation, theme scoping, linked shops and live balances. This is a selected Billing backend run, not a claim that its entire backend suite ran.

Browser checks covered source-gated workspace entry, main/sub-page contrast, checkout totals/action reachability on desktop and 844-by-390 landscape. The temporary unsaved QA line was removed and no invoice/payment was submitted. Signed-in Field Team Settings was checked at desktop and 390-pixel width using a separate disposable QA business, with its development-source warning visible. The clipped appearance card was corrected and rechecked. Temporary viewport overrides were reset and QA servers stopped after verification.

## Boundaries and deployment

This review does not establish a live Postgres/RLS deployment pass, a physical printer result, or a two-device production sync result. Deployed Billing and Field Team still need to be checked together for matching database/secret configuration, Pro entitlement, a synced customer/invoice and the handoff/collection cycle. Never merge the two real local databases to simulate that cloud topology.

These changes were verified as local working-tree changes before publication.
The user later authorized pushing the complete reviewed batch to GitHub and
Hugging Face; see the cloud-readiness continuation for the final UI checks.
No Cloud Run deployment or production database operation was performed during
the review.
