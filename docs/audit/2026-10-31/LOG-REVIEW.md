# Pasted startup and cloud-error log — 31 October 2026

The supplied log starts on 29 October and records an older running deployment.
It is evidence of that deployment's behavior, not proof that the current local
changes have been deployed. The original log remains in the private attachment;
no raw log, merchant profile, token or connection string is copied into source.

| Finding | Interpretation | Current action |
| --- | --- | --- |
| Repeated `QueuePool limit of size 3 overflow 2 reached` | Requests exhausted the five available connections and waited 30 seconds. Several dashboard endpoints consequently failed. | Corrected nested connection acquisition in notifications and data-transfer inspection; added a bounded one-connection regression. Pool exhaustion now produces a sanitized 503 with `Retry-After: 5`. |
| M-7: one invoice has receipts exceeding its billed total | Existing receipt attribution or imported history is inconsistent. This is a financial discrepancy, not an instruction to manufacture debt or credit. | Preserve rows and reconcile against original receipts. No production payment was deleted, moved or fabricated. |
| M-11: two operators have multiple open shifts | The log reports three and five open shifts respectively. Historical cash close counts are missing. | Retain shift history. Reconcile each shift's receipts and physically counted cash, then close through the supported register workflow. Do not auto-close with a calculated cash count. |
| Overfill: 18 invoice headers disagree with their line totals | Existing line-item corruption remains despite guards preventing new overfills. | Startup now directs the operator to a read-only report and original-document review, rather than suggesting an immediate `--apply`. No historical line was changed. |
| Missing/malformed authorization and deleted token subject | These are rejected unauthenticated or stale sessions. The log alone does not establish an authentication defect. | Deleted/retired users remain denied. Reauthenticate an active account; do not restore a deleted identity merely to silence the log. |
| No cloud token store on the cloud host | The desktop log relay found no provisioned device token. | The relay is now SQLite/desktop-only and does not attempt this workflow on PostgreSQL hosting. |

## Connection correction

`routes/alerts.py` inspected `db.bind` after the request session already held a
connection. Engine inspection requests another connection. Enough concurrent
polls can each hold one connection while waiting for another, exhausting a small
pool. The request now inspects `db.connection()`, sharing its transaction and
tenant context. The same nested acquisition was removed from data-transfer
table/column inspection.

The regression reserves the only connection in a pool of size one with zero
overflow, then reads real Field notification rows and tenant-scoped export
metadata. It asserts the expected Field result and that the connection returns
to the pool. Separate HTTP tests verify temporary exhaustion returns 503 and
unexpected failures return a generic 500 without internal exception text.

This is a demonstrated code defect and contributor to pool exhaustion. The log
does not prove that every production timeout had this sole cause. Validate the
deployed fix under concurrent dashboard polls and inspect pool occupancy,
long-running transactions and provider connection limits before tuning capacity.

## Additional ownership correction

Final startup review found a separate unconditional `business_id = 2` assignment
for NULL-owned invoices, inventory, payments and uploads. Local integer 2 cannot
establish ownership. Startup now reports counts and preserves these rows for an
explicit evidence-backed owner mapping. A regression proves all four families
remain unchanged. The supplied log does not establish whether any such rows
exist in the live database or were previously reassigned.

## Remaining data work

1. Complete the confirmed credential rotation in [SECURITY-RESPONSE.md](SECURITY-RESPONSE.md).
2. Take a restorable private backup and verify recovery into an isolated database.
3. Produce read-only discrepancy reports from the intended database and match
   each receipt, shift and invoice to its original source evidence.
4. Review a specific repair mapping and before/after financial, stock and journal
   expectations. Verify both hybrid copies and sync implications before applying
   changes. Insertion order or a coincidentally matching total alone is not
   approval to delete financial history.
5. Re-run invariants and reconcile reports after an approved repair. Keep recovery
   evidence outside Git and build contexts.

These live-data steps remain open. Current code verification and the original
40-issue implementation ledger do not certify the historical database clean.
