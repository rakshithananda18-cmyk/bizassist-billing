# Field Team, release controls and plan reconciliation — 30 October 2026

Baseline: `f90ea1f8de4be2b44cf2144954692a1094f08dab`. Date uses Asia/Kolkata. This is an audit, not a remediation release. Product source and real business databases were not changed.

## FT-01 — P1: reopening a cancelled task bypasses invoice collection exclusivity

**Evidence:** `backend-task/app/routers/tasks.py:143`, `:147-174`, `:248`; `backend-task/app/invoices.py:106`, `:193-228`.

Creation locks the selected Billing invoices and checks that another live task of the same kind does not already carry them. Cancellation removes a task from that check. The update endpoint subsequently permits `status="pending"` and assigns it directly; it neither locks the invoices nor repeats the exclusivity/balance validation.

Reproduction against the actual handlers and a synthetic in-memory SQLite database:

1. Create collection A linked to a ₹100 unpaid invoice.
2. Cancel A, then create replacement collection B for the same invoice.
3. Reopen A with `PATCH /api/tasks/{id}` and `{"status":"pending"}`.
4. Complete A and B with ₹100 collected each before Billing confirmation.

Observed: both tasks finish `done`; reported collections total ₹200 against ₹100 due. This does **not** establish that Billing posts a double receipt: its separate confirmation command has further guards. It establishes that the Field collection evidence/reservation invariant is broken, allowing staff to act twice on the same unpaid bill.

**Fix:** define allowed task transitions centrally. Reopening invoice-linked work must resolve and lock the same invoice rows as creation, revalidate customer identity/current due and the absence of another active task, and check the parent run/stop state. Add real PostgreSQL reopen-versus-create/complete races. Do not rely solely on UI hiding a reopen button.

Proof: [reproduce-field.py](reproduce-field.py). Successful result: `cancelled_task_reopened_despite_replacement="pending"`, statuses `["done","done"]`, `invoice_due=100`, `reported_collected=200`.

## OPS-01 — P1: the legacy repair command can fabricate invoice details

**Evidence:** root `repair_line_items.py:19`, `:57-66`, `:101-114`.

When a same-number donor cannot be found, the script chooses any invoice from the same business whose total is within ₹0.05, takes the first match, copies its line items into an empty `LCL-*` invoice, and commits. Equal totals do not establish document identity. The script targets `backend/bizassist.db` directly and has no dry-run/apply separation, explicit target argument, approved mapping, or pre-repair snapshot.

A synthetic database with `LCL-MISSING` and an unrelated ₹100 donor is sufficient: the unmodified script commits the donor's unrelated medicine line into the missing invoice. No actual business database was opened for this proof.

**Fix:** retire this command from operational use until it requires an explicit target and reviewed source-UID mapping, refuses ambiguous donors, defaults to dry-run, emits a reversible snapshot, and checks line/header/accounting invariants. Financial reconciliation must preserve uncertainty rather than guess the item list.

Proof: [reproduce-repair.py](reproduce-repair.py), exit 0 with `unrelated_donor_copied=true`.

## OPS-02 — P1: financial repair snapshots are tracked in the source repository

**Evidence:** three tracked `backend/voided_payment_*.json` files, introduced by `feb0c5f` on 1 August; generator `backend/scripts/void_duplicate_payment.py:227-249`; ignore rules `.gitignore:105-108` cover other repair exports but omit this filename family.

The snapshots contain invoice IDs/business IDs, invoice and receipt amounts, payment metadata, ledger-before rows, and restore SQL. They are operational repair exports, not declared synthetic test fixtures. The generator itself explains that such an export can be the only surviving record of a voided payment and warns against committing customer payment history. Only field names, types and fixture-marker presence were emitted during this audit; the financial values were not copied into these reports.

**Confirmed:** the financial records are version controlled. **Not verified:** current remote visibility, who accessed them, or whether every underlying row is real rather than synthetic. Treat them as private operational evidence until their provenance is established; do not infer a confirmed public breach from this local finding alone.

**Fix:** preserve the original repair evidence in an access-controlled encrypted archive, remove operational exports from future source/build contents, ignore `voided_payment_*.json` at any depth, and scan other tracked artifacts for business data. Assess copies in published repositories/images and coordinate any necessary history cleanup separately. Do not simply delete the sole restoration evidence.

## CI-01 — P2: some applications and shared contracts escape routine CI

**Evidence:** `.github/workflows/ci.yml:191-201`; `.github/workflows/field-team.yml:12-29`; `.github/workflows/release.yml:114-120`; `.gitleaks.toml`.

The normal frontend job tests Billing and AI. Admin's tests/lint/build are absent from that job, and normal frontend production builds are not all required there. Desktop tag packaging builds some assets, which is a different trigger and acceptance gate. The Field workflow has useful SQLite, PostgreSQL, image, real-model and restricted-role tests, but its Billing dependency filters list only four specific files. Changes to `backend/core/models.py`, Billing balances/collection logic, account purge logic, or Billing migrations can alter Field contracts without triggering that workflow. The real-model contract job uses `create_all`, so it does not demonstrate that the Billing migration chain installs all production policies.

**Fix:** require an application matrix for test/build and adopted lint rules, broaden Field shared-contract triggers, install the real migration chains into an empty PostgreSQL database, and exercise real login/payment/sync/Field requests as the intended runtime role. Keep the existing isolated RLS tests as additional tests. Secret scanning has a local hook/config; a required CI secret scan is not present in these workflows. Dependency vulnerability and license advisories were not fetched in this audit.

## DOC-01 — P2: historical roadmap text is still mixed with current execution state

The lean `docs/MASTER_PLAN.md` correctly qualifies live verification and was reconciled on 28 October. The full ecosystem plan, Foundation, architecture options and several execution plans retain historical descriptions that contradict later shipped choices or current risk evidence. Examples:

- `backend/FOUNDATION.md` still labels purchase, connection and subscription as future phases, and says Phase 1 is being built.
- The June architecture recommends Tauri and avoiding Electron, while the current repository deliberately contains an Electron release pipeline. That old recommendation is historical context, not a reason for a new rewrite.
- `docs/MASTER_PLAN.md:71-72` still asks about invoice-table reuse after the implementation already uses `invoices`.
- The invoice-template status board is dated July; the Sales decomposition plan's old line counts and pending steps cannot be treated as today's backlog without verification.
- Earlier reviews call money integrity excellent and exactly-once sync established. Today's reproduced bypasses show that a named green unit test is insufficient evidence for those system-wide claims.
- Historical data counts and financial discrepancies in July/August/29-October reports are not current database measurements. This audit did not inspect or repair real books.

**Fix:** keep the historical plans, add a clear superseded/current marker, and use a single short execution tracker with links to dated evidence, release SHA, open issue IDs and acceptance gates. Avoid erasing historical decisions or restating implementation presence as verified operation.

## Original intent and what remains missing

The original chat **“Add billing system”** was read, including the owner's pain points and the later clarification that every distributor, wholesaler and retailer both buys and sells. The chat **“Audit repository security and health”** was also sampled; its recent turns concerned UI/local previews. The repository's plans and 28–29 October audits supplied the more useful technical history. Conversation review was selective, not a claim to have read every earlier chat turn.

| Intended result | Current evidence | Remaining acceptance criterion |
|---|---|---|
| Fast billing that replaces an owner's current system | POS, invoices, payments, stock, reports and templates are substantially implemented | One paid pilot's documented parallel run, closing reconciliation and physical print acceptance |
| One business app for the entire trade chain; private books and shared deals | Shared BizID, connections/catalogue/orders/shared documents exist; Field is a deliberately separate service on the shared cloud database | Complete a supplier → buyer cycle while demonstrating all prohibited partner data stays hidden, including direct-ID requests |
| Stock ledger is truth; cache can always be rebuilt | Append-only ledger and cache rebuild code exist | Exact equality across batch/godown/NULL buckets; today's domain reproduction violates it |
| AI advises; deterministic commands own money | Layered AI router and human confirmation exist | Confirmed AI actions must use the same payment/lock/idempotency commands as POS; today's mark-paid bypass violates it |
| Cloud-authoritative, durable offline replay | Outboxes, UIDs, conflict handling and delta pulls exist | Account changes, cursor ties, writes during reads, partial failures and process restarts cannot lose or misattribute a document |
| Ordered transactional sync feed | Explicitly designed in `REALTIME_SYNC_ROBUSTNESS_PLAN.md` Phase 2 | Implement same-transaction change capture and safe ordered replay; schema presence and passing unit tests alone are insufficient |
| Supplier bill upload eliminates retyping | OCR/review/commit path exists | Pilot's representative actual supplier invoices map correctly, including pack-unit costs, before final confirmation |
| Billing and Field use the same online identity and balances | Derived staff token key, Pro/cloud gate, shared read adapters and Billing confirmation contract exist | Authenticated two-service workflow with actual policies/role, plus duplicate/reopen/cancel races and phone GPS checks |
| Recoverable data and honest deletion semantics | Backup/import and tombstone/reclaim code exist; limitations documented | Restore a fresh complete deployment and reconcile money; cloud account deletion must not be advertised as remote offline erasure |

The technical priority is an **enforced transaction boundary for money/stock plus a durable, correctly ordered synchronization protocol**. The operating priority is a release gate that proves those properties on the shipped topology. The business priority is evidence of the paid daily workflow and repeat ordering: the repository contains a pilot playbook, but no current signed-off pilot result was established by this review.

## Field application coverage and limits

Screened all tracked Field API/PWA files, shared contracts, deploy configuration, tests, and the root scripts/workflows/plans assigned to this reviewer. Deep traces covered authentication/device/session/Pro boundaries; task planning/update/completion; invoice balances and collection confirmation; requests, routes, attendance and tracking; frontend API/session isolation and GPS replay. Binary icons/sample images were inventoried, not semantically or visually validated.

Yesterday's fixed global GPS buffer, non-finite-input, duplicate completion, concurrent planning, credit-adjusted balance and business-deletion defects were **not** repeated as today's new findings. Relevant tests and implementations remain in place. The separate reopen transition bypass is today's additional finding.

Field requests remain manual item notes; they are not automatically converted to Billing order/sale drafts. That bridge is an explicit future capability in `FIELD_TEAM_MASTER_PLAN.md`, not an unexplained failure of a completed flow. Browser GPS pauses in the background; the code and plan honestly state this. Wake lock and a desktop test do not establish locked-phone continuous tracking.

Current checks:

- Field frontend: **68 passed / 16 files**; production build passed, JS 471.40 kB / 138.90 kB gzip.
- Public-release-check unit tests: **8 passed, 26 subtests passed**; no production probes were sent.
- Whole tracked tree: 1,261 files, 315,315 text lines by inventory convention, 13 binary files; Python AST and JSON screening found no parse errors.
- FT-01 and OPS-01 reproductions completed using synthetic databases and no external network.
- Field backend full SQLite suite: **153 passed, 10 skipped, 0 failed / 163 collected**, exit 0, 93.203 seconds. Six skipped Billing source-contract/deletion-lifecycle checks were then exercised against a fresh actual Billing-model SQLite schema: **6 passed**, exit 0. The remaining four unexercised gates require PostgreSQL tenant/role and concurrency checks. Initial sandbox runs stalled at the local TestClient socket prerequisite; the successful guarded runs used the same network restrictions outside that Windows restriction. This is not a deployed PostgreSQL result. See `field-test-results.json`.

Not established here: a production CI run for this exact SHA, deployed role grants, live PostgreSQL application behavior, authenticated browser/mobile day, physical printer output, full restore drill, current production data reconciliation, current dependency advisories, or actual pilot payment/retention. These are verification boundaries, not claims that the underlying deployment is broken.
