# BizAssist complete-code audit — 30 October 2026

**The most important missing thing is an enforced financial and identity contract across the whole product, proved by a repeatable end-to-end release gate.** The code has substantial billing, accounting, stock, sync and security foundations. Several entry points bypass those foundations, and some projections disagree. More features will make that harder to unwind.

The next structural investment is the **durable transactional change feed already specified in the realtime plan**. It must have correct commit visibility and acknowledgments; changing timestamps to an unchecked sequence is not sufficient. The next business milestone is the original **paid daily-billing pilot with reconciled books**, followed by repeat orders from a small connected trade chain. This review established no current signed-off pilot result; it does not claim that no pilot has ever happened.

## Audit basis and result

- Date: **30 October 2026, Asia/Kolkata**.
- Snapshot: **`f90ea1f8de4be2b44cf2144954692a1094f08dab`**; tracked working tree was clean when review began.
- Review team: primary reviewer plus **three parallel agents**, covering backend domain/AI, trust/sync/operations, and Billing/Admin/AI/Landing. The primary reviewer covered Field Team, scripts/CI, history/plans and consolidation.
- **1,261 tracked files**, 315,315 text lines by inventory convention, **13 binary files**. Every baseline file has a review/inventory entry; the final union has **zero unassigned files**.
- **40 prioritized records: 21 P1, 17 P2, 2 P3.** These include code defects, previously acknowledged missing workflows and release gaps. **TS-06 is explicitly conditional on the runtime role**; a live production RLS failure was not observed.
- Product code, real financial records and deployments were not changed. The deliverable is this audit, its evidence, and an execution plan.

P1 means close the issue before relying on the affected financial/security workflow. P2 means a material correctness/reliability gap. P3 means lower-impact release/installer hygiene. The counts are issue-register records, not a count of confirmed production incidents or a claim that every P1 has the same blast radius.

## Findings to address first

| Priority / IDs | Observed behavior | Why it matters |
|---|---|---|
| P1 **WEB-01** | During logout/login, A's running offline queue can send A's next invoice with B's token and remove it from A's queue | Cross-business attribution and data loss; reproduced with actual client modules and mocked network |
| P1 **WEB-02** | B's payment-share message can carry A's device-global UPI recipient; a hardcoded fallback can also override a valid Profile VPA | Collection can request the wrong recipient; reproduced without sending a message |
| P1 **BD-01 / BD-09** | AI mark-paid sets status without a receipt/journal; standalone advance replay adds credit twice without a durable receipt | The app can claim money effects that were never posted |
| P1 **BD-02 / BD-03 / BD-10** | Stock ledger 11 can display cache 23; a ₹120 carton of 12 pieces can become ₹1,440 of stock value; historical profit uses current cost | Stock, valuation and prior-period profit cannot be trusted across these paths |
| P1 **TS-01–03** | Timestamp page ties, writes during reads and combined unread-table/rejected-row states can skip sync data | A successful-looking pull can permanently miss committed records |
| P1 **TS-04 / TS-05** | Successful staff replication does not revoke the old cloud session; failed staff/profile pushes have no durable retry | Local staff/security changes need not take effect on cloud |
| P1 **BD-04–07** | AI counts returns as revenue/cash; re-sealing makes altered journal contents verify; B2B taxes differ between order/invoice; direct IDs bypass catalogue restriction | Advice, integrity alarms, amounts and partner privacy disagree with intended contracts |
| P1 **FT-01** | Cancel collection A, create B, reopen A: both can report ₹100 collected for the same ₹100 bill | Collection reservation is checked on creation but bypassed on reopening |
| P1 **OPS-01 / OPS-02** | Legacy repair guesses donor lines by equal total; operational invoice/payment/ledger repair snapshots are tracked | Unsafe reconciliation and private-evidence custody need attention; remote publication was not verified |
| Conditional P1 **TS-06** | Login/signup and separate plan sessions do not establish the context required by the declared constrained FORCE-RLS role | Requires a full-schema runtime-role test and explicit bootstrap design; using a privileged role can mask the gap |

All **40** records, including lower-priority UI/search/state/installer findings, are in the [issue register](issues.csv) and [machine-readable JSON](issues.json). Exact source lines, triggering conditions, remedies and evidence limits are in the detailed reports. Existing open findings were rechecked and tagged; yesterday's fixed issues were not blindly copied forward.

## Where the earlier plans stand

The original chat **“Add billing system”** described the owner's need for fast local/cloud billing, less manual stock entry, supplier-invoice upload, staff usability and a private connected ordering flow. Its later clarification established **one business app for every buyer/seller in the trade chain**, rather than a permanently separate second-class retailer app. Selected recent turns of **“Audit repository security and health”** were also read; those turns concerned UI/local previews. Repository plans and dated release notes supplied most technical decision history.

| Intended direction | Today's assessment |
|---|---|
| Billing first, supplier auto-entry next, connected trade next, AI as a paid layer | Still the right product sequence; implementation breadth has outrun proof of the complete daily money cycle |
| Money is deterministic, append-only and owned by atomic/idempotent commands | Good command implementations exist, but legacy AI actions, advances, valuation and readers violate the system-wide contract |
| Stock ledger is truth and inventory is rebuildable | Present in design/code; exact NULL/batch/godown projection semantics need correction |
| Private books, policy-limited shared deals | Core design remains sound; direct order commands must enforce the same catalogue policy as listings |
| Cloud-authoritative offline replay | Outbox/UID/conflict mechanisms exist; current cursor/account-lifecycle holes need correction |
| Ordered same-transaction change log with gap recovery | Explicitly planned in `REALTIME_SYNC_ROBUSTNESS_PLAN.md` Phase 2, still missing; it addresses today's demonstrated loss cases |
| Encrypted offline database/backups, rehearsed restores, controlled signed updates | Ordinary SQLite/plain JSON paths remain; secret wrapping is different. Current deployed storage encryption, installer signatures and restore recovery were not established |
| Every completed phase has named tests and operational proof | Unit evidence is extensive; the cross-app identity/money/reconnect/restore gate remains incomplete |

The historical plans should be preserved and clearly marked. The June architecture's Tauri option, July template/decomposition boards, and old “excellent integrity/exactly once” assessments are not today's release state. Use the [execution plan](PLAN.md), current issue IDs, and dated test evidence to update the lean master tracker after fixes.

## Validation completed today

These are separate runs with overlapping scope. **Do not add their counts together as unique coverage.** Passing tests demonstrate their assertions; they do not disprove separately reproduced defects.

| Check | Result / scope |
|---|---|
| Billing frontend full suite | **869 passed, 1 failed / 111 files**. Failure is the old notification-heading assertion; focused rerun fails identically. No navigation defect follows from that assertion alone |
| Admin frontend | **47 passed / 3 files**; production build passed; lint **268 errors, 14 warnings** |
| AI frontend | **13 passed / 1 file**; production build passed; additional isolated component proofs demonstrate streaming/auth gaps |
| Field frontend | **68 passed / 16 files**; production build passed |
| Billing production build | Passed, with a main-chunk size warning |
| Landing build | **Unverified**: local Vite dependencies absent; no source failure or advisory conclusion inferred |
| Selected backend money/API workflow suites | **139 passed, 1 skipped**, 18.82 seconds; nine existing modules, worker-isolated SQLite. Journal/day-book reference comparison skipped because a payload exposed no comparable reference |
| Backend pure/helper/unit selection | **328 passed**, 16.72 seconds; not an HTTP/Postgres pass |
| Full Field backend SQLite mirror suite | **153 passed, 10 skipped / 163 collected**, 93.203 seconds |
| Field/Billing actual-model contract and deletion follow-up | **6 passed** on fresh actual Billing-model SQLite; four remaining Field gates require PostgreSQL RLS/row-lock concurrency |
| Existing partial-pull tests | **10 passed**, despite missing the demonstrated combined-failure production branch |
| Backup helper tests | **8 passed**; mocked helpers, no real restore |
| Public-release-check unit tests | **8 passed, 26 subtests passed**; no production probes sent |
| Defect proofs | Ten domain behaviors, four trust/sync behaviors, client outbox/payment/AI proofs, Field reopen and legacy-repair cases asserted against current code with synthetic state |
| Static source checks | Tracked Python/JSON parses passed; Alembic graph has one head across 42 Billing revisions |

The Windows sandbox stalled the local socketpair used by TestClient. Successful workflow/Field runs used guarded commands outside that restriction, with synthetic credentials, disposable databases and external networking blocked. Stalled audit processes were stopped. No dependency installation, production repair, authenticated live-cloud transaction or deployment occurred.

## Coverage honesty

[File coverage](file-coverage.csv) contains every baseline path, size, hash, parse/screen result and contributing reviewer ledger. The strongest evidence per file is: **189 targeted source traces, 113 test files exercised, 946 automated/test-source screens, 13 binary metadata reviews**. A targeted trace means relevant flow/contract analysis, not proof that every line of that file is correct. Test-file coverage does not imply every test passed or no case skipped.

Ignored environments/dependencies, generated build outputs, local runtime databases, uploads and private scratch data were not treated as product source to audit. Tracked generated/repair artifacts were inventoried, with sanitized inspection for financial exports. Binary assets received metadata review, not visual certification. This is whole-tree inventory and risk-based deep auditing, **not a claim of manually proving all 315,315 lines**.

Not established: deployed runtime grants/RLS, full backend collection, live multi-server/offline/device soak, actual printer output, a restored full deployment, historical production reconciliation, installer signature state, current dependency advisories, or paid-pilot adoption. Those limits appear as explicit plan gates rather than unsupported green stamps.

## Deliverables

- [Prioritized execution plan and acceptance gates](PLAN.md)
- [Issue register](issues.csv) · [JSON](issues.json)
- [Complete file-coverage ledger](file-coverage.csv) · [coverage summary](coverage-summary.json)
- [Backend business/accounting/AI audit](backend-domain.md)
- [Security, sync, persistence, desktop and backup audit](trust-sync-ops.md)
- [Billing, Admin, AI and Landing audit](web-apps.md)
- [Field Team, CI, repair tools and prior-plan reconciliation](field-release-plans.md)

Reproduction scripts and sanitized results are beside these reports. They assert current bad behavior; when fixing an issue, convert them into regression tests that assert the corrected contract. No fixes are implied by a proof script exiting successfully.
