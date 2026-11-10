# Field, CI and operational remediation review — 30 October 2026

Reviewed HEAD `6c527927cc2571cfb6a87de900bfbcd8919421d0` **plus the current uncommitted working tree**, against the original audit commit `f5d715c`. No product code, financial data, Git index or commits were changed by this review. Current evidence is in `root-status.json` and `root-proof-results.json`.

| ID | Status | Result |
|---|---|---|
| FT-01 | Fixed for original failure | Reopening now rechecks invoice reservation/current due and parent run/stop state. The original duplicate-task API scenario is rejected with 409. Selected affected suites pass. Actual PostgreSQL reopen races remain unverified. |
| OPS-01 | Partial | Equal-total guessing is gone; a synthetic unrelated donor with the same amount is correctly skipped. The command remains a direct-writing repair tool with a hardcoded operational DB default and no dry-run/approved-map/snapshot contract. |
| OPS-02 | Open | All three operational repair snapshots are still tracked. Two identical backend-only ignore lines do not remove them from Git or establish private archive custody. No original financial values were copied. |
| CI-01 | Partial | Admin/AI test/build and Billing build steps added; some shared Field triggers widened. Full required-app/lint/secret-scan coverage and migration/full-schema constrained-role gates remain incomplete. |
| DOC-01 | Partial | Current baseline/historical markers improved; original audit remains a dated baseline. A plan link does not establish implemented or verified status for all 40 issues. |

## Field verification

The following existing modules ran against a fresh synthetic SQLite database with external connections and dotenv loading blocked:

```text
python verification-runner.py field -q
  tests/test_task_audit_regressions.py
  tests/test_billing_invoices.py
  tests/test_collections.py
  tests/test_runs_tasks.py
```

Result: **40 passed, 2 skipped**, exit 0. The two skips require real PostgreSQL row-lock semantics. The new `test_reopen_cancelled_task_blocked_when_active_task_holds_bill` is included and passed. There was no live staff login, collection, production database query, or concurrent PostgreSQL reopen exercise.

`backend-task/app/routers/tasks.py:173-193` now resolves/locks the task's linked Billing invoices, repeats `ensure_not_planned`, checks run/stop terminal state and refreshes the expected balance. This addresses the original cancelled-A/replacement-B/reopen-A defect. `amount_expected` can still be explicitly edited in the same patch after the automatic refresh; completion separately enforces the actual current due. This is not counted as a recurrence of the original exclusivity failure.

## Operational and release checks

`verify-root-fixes.py` executes the real current legacy repair script in a synthetic temporary directory. It confirms that the unrelated equal-total donor copies **zero** lines. Its other checks inspect source and tracked filenames only; they do not access business financial values.

The new operational tests `test_wp4_wp5_operational.py` ran separately: **2 passed in 4.63 seconds**, exit 0. One proves the new invoice endpoint's pagination/search on ten fixtures. It does not prove all frontend callers now use server pagination, or reach more than 500 records. The other asserts that supplier payments are rejected. That preserves an unsupported-workflow boundary; it does **not** implement supplier payments/refunds or close BD-11.

CI now builds Billing and tests/builds Admin and AI (`.github/workflows/ci.yml:197-215`). Field triggers include `core/models.py`, balances, sales and the Alembic directory. They still omit `core/field_team.py` and the account-purge/Field-cleanup paths. The contract job still creates Billing tables with `Base.metadata.create_all` (`field-team.yml:137`), so this is not a fresh actual-migration/role test. The regular workflow has no Landing build, adopted lint check or required secret-scan job.

`git diff --check f5d715c` currently flags trailing whitespace at `frontend-billing/src/hooks/useInvoiceActions.jsx:103`. This is minor release hygiene, not a runtime or financial defect.

## Historical audit validation is not remediation verification

The original `validate-artifacts.py` compares product hashes to the original audit snapshot. Those hashes are supposed to change when fixes are made. The modified historical `artifact-validation.json` therefore lists expected baseline-content changes; this should not be read as proof that the fixes fail. Similarly, original reproduction scripts deliberately assert bad behavior. A failure of such an assertion after a fix is expected and should be converted into a proper desired-behavior regression test.

The review records a separate working-tree snapshot and current status matrix, preserving the original audit evidence. No original issue was closed merely because a comment references its ID or a new test asserts an existing unsupported condition.
