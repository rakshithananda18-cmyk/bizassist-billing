# Billing and Field Team — complete app survey

Date: 29 October 2026. Scope: current shared checkout, including the user's recent
Billing, Admin and Field Team work. This report supersedes blanket completion
claims in older plans; it does not certify a live deployment.

## Decision

**The app is improved, but is not yet cleared for unrestricted financial use.**
The review found and corrected concrete registration, return, payment-validation,
page-state, Field privacy and concurrency defects. Separate accounting-model gaps
and live deployment/device checks remain. Passing tests on supported flows must
not be presented as evidence that an unfinished money sector is complete.

## First-time registration and the 14-day offer

- Every eligible first registration receives the fixed **14-day Pro trial** from
  the cloud. Local + Cloud is selected by default. The trial includes automatic
  Local + Cloud sync and Pro Field Team access; Field Team uses the cloud only.
- Fresh registration requires a valid, country-aware phone number on the form and
  API. Formatting equivalents identify the same phone. A legacy local mirror may
  omit an old account's phone so an existing owner can still sign in.
- Account creation and the trial grant commit together. A failed grant rolls back
  signup instead of leaving a first-time owner silently on the free plan.
- A private phone-fingerprint claim prevents another trial after account deletion
  or simultaneous registrations with the same number. Repeated-phone registrations
  explain that they are not first-time eligible. There is no automatic charge.
- Local-only billing records remain on the computer; identity registration connects
  to the cloud once. After the trial, Local billing continues; automatic cloud sync
  and Field access need Pro. Export/backup must remain available.
- Production trial length is fixed at 14; the legacy `PRO_TRIAL_DAYS` variable no
  longer disables or changes it. Tests explicitly mock unrelated trial grants off
  and use explicit phone-bearing signup fixtures, rather than a production bypass.
- Phone format validation is **not ownership verification**. SMS/OTP verification
  and registration abuse controls are recommended before relying on one-phone
  eligibility as a strong identity guarantee. No SMS was sent in this review.

Deploy the new `trial_phone_claims` schema (Alembic revision
`e0a1b2c3d4e5`) with a backup. Verify the cloud's subscription enforcement setting:
the supplied startup logs showed enforcement disabled. The expiry/gating tests
prove behavior with enforcement enabled; they do not prove the live Space has
that configuration. This review does not silently change a live account's plan.

## Three detailed agent surveys

| Survey | Coverage | Detailed record |
|---|---|---|
| Billing pages | Every route/subpage, shared navigation, page loading/errors, themes, settings, notifications, returns presentation and cross-app entry points | [Billing page matrix](2026-10-29-billing-pages-agent-audit.md) |
| Money sectors | POS/PS checkout, tenders/change/credit, receipts, invoice and purchase returns, customer/vendor balances, expense/journal/report/stock/shift behavior and financial sync boundaries | [Money sector matrix](2026-10-29-money-sector-agent-audit.md) |
| Field Team | Owner and worker pages, Billing identity/Pro gate, tasks/runs, collections/proof/GPS, privacy, planning/completion concurrency and shared-cloud account cleanup | [Field page matrix](2026-10-29-field-app-agent-audit.md) |

The three agents were restarted when the user requested it; they continued their
saved work rather than replacing prior edits. Their reports distinguish source
review, component/API tests and real PostgreSQL evidence. Existing user edits were
preserved. No production bill, payment, return, phone claim or business deletion
was created by the survey.

## Confirmed fixes in this review

| Area | Corrected behavior |
|---|---|
| Signup | Mandatory phone, fixed 14-day first-time grant, atomic account/trial, durable duplicate-phone protection and clear repeated-phone fallback |
| Money input | Finite amounts are required across payment/expense/return/shift and Field collection boundaries; invalid JSON numbers receive safe errors |
| Returns | Source document locks and quantity checks prevent duplicate/excess requests; cumulative saved discount/tax/cess/rounding allocations keep full returns tied to the actual bill |
| Balances | Linked returns reduce collectible/customer/vendor obligations; paid returns are exposed separately from cash refunds or banked advances |
| Journals and reports | Return postings/reversals and net profit/revenue projections are checked together; unsupported supplier-payment entry is blocked rather than posted as a customer receipt |
| Cash and stock | Shift posting/close serialization and fractional inventory-cache handling are strengthened |
| Billing pages | Fixed broken Dashboard routes, stale Home figures, several failure-as-empty/zero states, Settings initial retry, notification false all-clear and missing rail-mode subpage tabs |
| Field integrity | Task null/date/reassignment guards; serialized completion/planning; session-scoped GPS buffers and retries; centralized Billing signup entry |
| Shared cloud deletion | Billing and Field business cleanup share the owner's transaction; the other business's data must remain intact |

Earlier import fixes remain in the checkout: B2B duplicate recognition and financial
conflict rollback, SQLite outer transaction protection, explicit partial-import
results, migration validation/save checks, catalogue-reference-safe purge, and the
prepared Docker model-cache permissions fix. See the [import/lifecycle review](2026-10-29-sync-import-lifecycle-review.md).

## Remaining release priorities

1. **Durable standalone customer advances.** Pure prepayment without an outstanding
   invoice needs its own append-only receipt, idempotency anchor, liability posting,
   shift/cash attribution and sync identity. A mutable customer credit balance alone
   is insufficient. Do not describe this sector as fully audited or robust.
2. **Supplier payment ledger.** Blocking the misleading entry prevents a customer
   receipt mispost; it does not implement supplier settlement. Add a dedicated
   idempotent supplier-payment command, vendor/bank journal and receipt before
   enabling the form. Review any historical use separately.
3. **Historical cost snapshots.** Profit/COGS must use cost captured when the sale
   posts, not today's editable catalogue cost. Add immutable line/stock cost
   snapshots and a deliberate policy for legacy records; do not guess old costs.
4. **Cash/bank refund records.** A credit note records the obligation to refund or
   credit a customer; it does not record money leaving the drawer or bank. Add a
   linked append-only refund command with idempotency, operator/shift attribution
   and accounting. Do not label an unposted payout as money refunded.
5. **Return line identity and quote.** Product-only returns are deliberately
   rejected when the source has multiple lines for that product. Add source-line
   UID selection and a read-only server quote before supporting ambiguous batch /
   price / serial returns and exact cumulative previews. Debit-note numbering also
   needs a durable sequence and database uniqueness.
6. **Page failure states and scale.** Stock, Purchases and the shared invoice list
   still have required-read paths that can appear empty after failure. Fixed 500-row
   fetches can hide later records. Use explicit unavailable/retry states and server
   pagination/search/counts before claiming complete large-business support.
7. **Production reconciliation.** The supplied overpaid receipt, duplicate open
   shift and overfilled-document findings remain existing-data work. Compare the
   correct database backup with receipts and counted cash. No balances or closing
   cash were guessed or repaired in production here.
8. **Deployment and real-device evidence.** Verify both deployed apps against the
   same business, trial expiry/Pro flags, backup restoration, two terminals and a
   real offline/reconnect cycle. Test checkout receipt/retry on actual A4/thermal
   printers and scanners. Cloud-to-local account retirement still needs a verified
   signal/backup/acknowledgement design; deleting the cloud account does not wipe an
   offline desktop copy.

The shared-cloud cleanup also requires full reference visibility under RLS; it
returns a clear 409 instead of guessing safety when the connection is restricted.
Verify the deployment's maintenance/admin connection permissions and supported
Field schema before treating a test superuser's successful purge as production
evidence. It never disables RLS as a shortcut.

## Verification limits

Test counts and final integrated results follow below. Runs overlap and are not
additive. Local SQLite and cloud PostgreSQL tests use disposable databases; the
two real local databases were not merged or repointed. Field's actual-Billing-schema
PostgreSQL suite verifies the shared database contract separately from its own
standalone fixtures.

This pass includes a source/component/API survey for every listed page; it is not
an authenticated live-browser walkthrough of every page. The in-app browser could
not attach a fresh webview during this pass, so the current mandatory-phone UI is
covered by isolated component tests rather than a new browser screenshot. Earlier
registration responsive-browser evidence is in the prior dated review. Docker and
physical printer verification remain separate deployment tasks.

Changes remain local; this survey did not commit, push or deploy them.

## Completed integrated verification

| Check | Result |
|---|---|
| Billing frontend full suite | **868 passed / 111 files** |
| Final registration/contact/hosting frontend set | **31 passed / 3 files**, including missing phone, canonical country codes and repeated-phone explanation |
| Billing production build | Passed; existing bundle-size warning remains |
| Admin frontend, unchanged since its reviewed wipe-copy change | **47 passed / 3 files**, build passed; see the earlier dated record |
| Signup/trial + purge on real PostgreSQL | **26 passed**, including concurrent registrations with one phone |
| Integrated SQLite signup/import/purge/financial-sync set | **92 passed, 2 engine-specific skips** |
| Broad money-sector SQLite set | **267 passed** before final balance projection; final touched financial/balance set **169 passed** and projection subset **5 passed** |
| Final money regressions on real PostgreSQL | **36 passed**, including raw nonfinite JSON, saved return amounts and balances |
| Field frontend full suite and production build | **68 passed / 16 files**; build passed |
| Field full suite against actual Billing PostgreSQL schema | **151 passed**, before the final focused additions; contract and restricted-role RLS checks opted in |
| Final Field PostgreSQL touched sets | **20** task/GPS/finite-money/concurrency, **35** balance/receipt/collection/lifecycle, **29** invoice/run/planning; all passed |
| Shared-cloud Field deletion proof | **2 passed**: all 14 owned tables cleared, other business preserved, stale sessions denied; malformed cross-business references refused |

Field's detailed engine/contract sets are recorded in its linked audit. Runs
overlap; these counts are not a combined unique
test total. The entire Billing backend suite was not rerun and no passing backend
subset is represented as a full-suite result.

The disposable PostgreSQL cluster was stopped after verification. The review did
not alter or stop the user's PostgreSQL service or either real local database.
