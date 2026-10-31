# Remediation verification — 30 October 2026

**18 fixed, 20 partially fixed, 2 open out of the original 40.** The changes close many of the original failure cases, but the whole set is not complete. Independent desired-behavior checks still expose money, account-identity and sync failures, including regressions introduced by the remediation.

Reviewed **HEAD `6c527927cc2571cfb6a87de900bfbcd8919421d0` plus the current unstaged/new files**, against audit commit `f5d715c`. The 62 changed/new paths captured at review start stayed unchanged during verification. This is a working-tree review, not a review of the two commits alone. Three domain agents and the primary reviewer checked every original ID. No implementation, existing test, original audit record, staged change, commit or remote was modified by this review.

Read the [all-40 status table](STATUS.md), [sortable CSV](issue-status.csv), or [JSON](issue-status.json) for every finding. The detailed reports contain exact current locations and proof conditions.

## Issues to address before calling this remediation complete

| Priority / ID | Current observed failure | Next change |
|---|---|---|
| P1 **BD-10** — unsafe historical cost migration and zero-cost return | `backend/database/migration.py:314` adds `cost_price DEFAULT 0.0` to existing lines; `reports.py:267` treats that as known historical cost. A predecessor-shaped line previously valued at cost 80 becomes reported COGS 0. A legitimate zero-cost sale returned after the product cost becomes 40 reverses at 40, producing net COGS −40. | Represent unknown historical costs separately from legitimate zero, add an explicit upgrade/reporting policy, and preserve zero snapshots on returns. Do not deploy or certify this upgrade as money-correct until those cases pass. No real books were inspected or corrected. |
| P1 **WEB-01** — original replay fixed, late enqueue still crosses accounts | An A checkout request can fail after logout/unmount/login B. `usePaymentFlow.js:306` then calls the current queue, and `syncManager.js:90` stamps A's bill with B's scope. The replay generation check correctly trusts that new B stamp. The real-hook probe reproduces this. | Capture immutable business/backend/session ownership before the first asynchronous request; enforce it during enqueue as well as replay, acknowledgment and failure recovery. Quarantine ambiguous old operations under A. |
| P1 **TS-05** — new control outbox does not yet provide safe durable delivery | Staff changes commit before their outbox event; enqueue itself commits the caller's transaction. Actual staff deletion sends `role:""`, rejected by the cloud schema. Older retries can overwrite newer successes; control-only pending work can be skipped. Pending old events also survive purge/rekey and send an old tenant profile using the recreated identity's token in a synthetic actual-purge/flush proof. | Commit mutation plus event together; validate real tombstones; preserve per-identity ordering/revisions; retry control backlog independently; clear/quarantine old-identity events on reclaim. Send and acknowledge durable event IDs and expose backlog health. |
| P1 **BD-06** — B2B tax/rounding still diverges | The basic 100+18% case is repaired. However, normal rounding quotes 118.59 and invoices 119. Changing buyer state after a same-state quote produces a final invoice of 100 with tax 0 instead of retaining or explicitly requoting the 18 tax. | Use one quote/invoice calculator and freeze the relevant destination/tax facts, or require a confirmed requote. Do not zero tax heads that final completion may later need. |
| P1 **TS-01 / TS-02** — new/new cursor repair is not a complete delivery protocol | Compound cursors deliver tied rows correctly with upgraded peers. A legacy timestamp client against the new server still loses the tied tail. A row committed after a pull with a timestamp two seconds behind its cutoff is absent from the next incremental pull. | Define mixed-version capability/recovery rules and a commit-visible durable feed. Request-start time plus a compound timestamp cursor does not prove eventual delivery of late commits. |
| P1 **BD-04** — financial readers still disagree | The simple full-return overview is fixed, but another deterministic handler and the AI prompt snapshot still report 200 revenue/100 collected for an unpaid 100 sale fully returned. A legacy collection 100 plus new receipt 10 reports only 10; a partially paid/returned invoice's overdue amount is still its gross 100 instead of 30. | Complete shared financial projections across every reader, use per-invoice legacy fallback, and keep actual receipts, credits and adjusted obligations distinct. |
| P2 **WEB-08** — newly added invoice error handling throws | `frontend-billing/src/components/payments/InvoicesListView.jsx:68` calls an undefined `logger` before setting `loadError`. The failure UI never activates; the isolated current callback throws `ReferenceError`. | Import/define the logger and execute failure-state tests, then finish stale-request/identity guards and remaining transfer error states. |

These are local synthetic demonstrations, not claims of production incidents. Source locations are verified against the reviewed working tree. Eleven records originally rated P1 remain unclosed, including **TS-06's conditional full-RLS deployment gap**; that is not proof that the live service currently uses the constrained role or fails authentication.

## What is verified fixed

| Area | Closed original IDs | Verified change |
|---|---|---|
| Backend financial/domain | **BD-01, 02, 03, 05, 07, 08, 09, 12** | Unsafe AI mark-paid and standalone advances are safely disabled/refused; exact stock buckets and carton/base-unit cost are corrected; hash alarms remain; direct hidden-product ordering is denied; terminal order transitions are protected; catalogue stock is summed. |
| Trust/sync/operations | **TS-03, 04, 07, 08, 09** | Unread-table cursor guard, receiver credential revocation/idempotent retry, failed-export refusal, actual desktop readiness and stable valid-secret/rejected-short-secret behavior. |
| Web | **WEB-02, 03, 05, 11** | Invoice sharing/reminders use the profile recipient and credit-adjusted outstanding; an existing AI tab clears its token on delivered storage logout; checkout QR is local. |
| Field | **FT-01** | Cancelled task reopening rechecks locked invoice reservation/current due and parent state; the original duplicate-task scenario returns 409. |

“Fixed” means the **original local defect is corrected or safely contained** in verified conditions. It does not mean all workflows are implemented, historical books repaired, every distributed race tested, or deployment certified. For example, AI payment execution and standalone advances remain unavailable; WEB-05 still needs real cross-origin notification-delivery acceptance; Field PostgreSQL reopen races remain unexecuted. Follow-up conditions are retained in the per-ID matrix rather than silently dropped.

## The two open records

- **BD-11:** supplier settlements, real linked customer refunds and return-credit allocations have not been implemented. The new test proves that an unsupported supplier payment is rejected; it does not supply those money workflows.
- **OPS-02:** all **three** financial repair snapshots are still tracked. New `.gitignore` rules do not remove already tracked files. Preserve private restoration evidence before removing operational data from future source/build contents; assess published copies separately. No financial values were copied into this review.

## Other partial changes

The [complete matrix](STATUS.md) credits working portions and lists remaining conditions. Important examples:

- **BD-13:** automatic debit-note numbering uses a durable allocator, but the unique index is model-only; an existing predecessor-shaped table still accepts two manual identical numbers. Add an actual upgrade migration and duplicate diagnostics.
- **TS-06:** the plan session is now tenant-bound, but login/signup/public/background bootstrap and real full-schema constrained-role verification remain incomplete.
- **WEB-04/06/07/10:** send locking, loopback hostname parsing, cache keys and merchant action identity guards improved. Old streams/loads can still refill a new session or route; SSO still lacks expected-window binding and the configured production-origin path.
- **WEB-09:** the backend now supports page/per_page/search, and its new test passes. The frontend does not use that interface; Contacts, Money and checkout still have capped datasets. Removing the invoice cap by fetching everything is not server pagination.
- **WEB-12:** existing tests are green, but Admin lint was made green by broadly disabling checks, including hook dependencies and unused variables. Landing build remains unverified. One trailing-whitespace check also fails.
- **WEB-13:** explicit Intel/Apple Silicon alternatives were added, but the generic primary Mac download can still choose arm64 on an unknown/Intel machine.
- **OPS-01 / CI-01 / DOC-01:** equal-total repair guessing is removed, test/build/trigger coverage widened, and history markers added. The repair's live-write safety contract, remaining CI/migration/role gates and broader current evidence ledger are not complete.

## Tests actually run

Runs overlap; do not add them as unique coverage. New review probes assert **correct behavior**. Their failures indicate unmet requirements, unlike the original audit proofs that deliberately asserted old bugs.

| Check | Result |
|---|---|
| Billing existing frontend suite | **871 passed / 112 files** |
| Admin / AI existing frontend suites | **47 passed / 3 files**; **13 passed / 1 file** |
| Billing / Admin / AI production builds | All passed; Billing retains a bundle-size warning |
| Admin lint | Passed under substantially relaxed rules |
| Landing build | Unverified: local Vite dependencies absent; no installation or source-failure claim |
| Selected backend current/new regression suite | **271 passed**, 37.10 seconds |
| Additional backend integration selection | **117 passed, 4 failed, 1 skipped**, 28.58 seconds |
| Field task/invoice/collection/run selection | **40 passed, 2 PostgreSQL-only skipped**, exit 0 |
| New operational tests alone | **2 passed**, 4.63 seconds; included in the broader backend selection |
| User's new WP2 tests | **6 passed** |
| Independent backend desired-behavior proofs | **10 expectations pass, 10 fail**; script records observations rather than equating exit 0 with success |
| Independent trust/sync desired invariants | **7 passed, 8 failed**; actual desktop probe additionally passes four cases |
| Independent web safe-behavior component probes | **3 passed, 4 failed**; original active-flush containment now passes; invoice callback separately throws undefined logger |
| Static review snapshot | Current changed Python syntax parses; implementation hashes/HEAD unchanged during the review |

The four integration failures are **stale fixtures**, not recurrence of the terminal-state bug: `backend/tests/test_phase4_sync.py:99-101` still jumps accepted→completed, while the newly enforced graph requires packed/dispatched. The current frontend and a valid-chain proof follow the graph. Update those fixtures and rerun their bilateral posting/exactly-once assertions; the current red run does not establish those downstream assertions passed.

All database/probe data was synthetic, using disposable SQLite, in-memory models and mocked external services. Field/HTTP runs used guarded execution outside the Windows socket restriction; external network access was blocked. No actual cloud role, live business books, real payment/refund, production restore, device soak, printer or deployment was verified.

## Next patch sequence

1. Correct **BD-10**'s upgrade/zero-cost semantics and **BD-06**'s destination/rounding contract before a money-layer release.
2. Finish account ownership at asynchronous enqueue (**WEB-01**) and control-event lifecycle/atomicity/order/retry (**TS-05**).
3. Complete commit-safe/mixed-version sync (**TS-01/02**) and shared financial readers (**BD-04**).
4. Fix the undefined logger; finish stream/cache/SSO/admin request ownership. Restore useful quality diagnostics and update the intentional B2B fixture transitions.
5. Install/verify the actual upgrade constraints, complete the remaining role/restore/CI gates, and deliberately bound or implement supplier/refund scope. Preserve and remove tracked operational exports through an explicit evidence-custody step.

The original audit and its hash validator remain historical evidence; their baseline hashes are expected to differ after code changes. This directory supplies the current per-issue verification record. It is not a code-fix or deployment commit.

## Detailed evidence

- [All 40 statuses](STATUS.md) · [CSV](issue-status.csv) · [JSON](issue-status.json) · [summary](verification-summary.json)
- [Backend business/accounting review](backend-domain.md) · [proof results](backend-proof-results.json)
- [Trust/sync review](trust-sync-ops.md) · [desired-invariant failures](trust-behavior-results.txt)
- [Web review](web-apps.md) · [archived synthetic web proofs](web-proof/README.md)
- [Field/CI/repair/data-custody review](field-ci-operations.md)
- [Reviewed source snapshot](reviewed-snapshot.json)
