# Remediation and latest-change review — 31 October 2026

This record continues the [30 October audit](../2026-10-30/README.md) and its
[40-issue verification](../2026-10-30/remediation-review/README.md). Those reports
describe earlier snapshots; their counts are not the current completion count.

The [current 40-ID ledger](implementation/STATUS.md) records **38 implemented
fixes and two safely contained workflows**. AI status-only payment changes and
standalone advances remain disabled; they are not completed features. This
record includes the user's latest working-tree changes and the multi-agent
review. The earlier 18-fixed/20-partial/2-open result is superseded for current
implementation status, while its historical evidence is retained.

The latest user changes include Field Team maps, task completion, score views,
navigation and styling. Review includes their payment destination and QR flow,
in addition to the original billing, accounting, identity and sync findings.

**Keep the Field changes with the targeted corrections now applied.** The
[keep/revert review](implementation/web-latest-changes.md) explains the merchant
VPA/local QR fix, map behavior, route access, GPS account ownership, request
validation and attendance labels. No screen or feature was blanket-reverted.

## Runtime and historical invoice behavior

The first pasted error is addressed by stable Auth/Lock context identities
across hot reload. The newer cloud log exposed nested database connection
acquisition: notifications and data-transfer inspection now reuse their request
connection. A pool-of-one regression passes, and capacity exhaustion returns a
sanitized retryable 503. See the [log review](LOG-REVIEW.md).

Deleting a business now preserves the other party's historical invoice and
shared B2B evidence. Documents show the immutable original business details and
a deleted-business notice. Private books are purged without transferring their
identity to a replacement account. Retired identities cannot log in or start new
trade. Tests cover deletion in both directions and a later credit note.

Startup also no longer guesses that NULL-owned financial rows belong to local
business 2. It reports them for explicit source-backed ownership review.

## Executed acceptance

| Check | Result |
| --- | --- |
| Complete Billing backend, isolated SQLite | 2,526 passed; 23 explicitly skipped; zero failures |
| Complete Field backend, standalone SQLite | 155 passed; 10 contract/PostgreSQL skips |
| Complete Field suite on Billing's fully migrated PostgreSQL schema | 165 passed; zero skips or failures |
| Fresh complete Billing frontend | 883 passed in 118 files |
| Fresh Field frontend | 89 passed in 22 files; production build passed |
| Full SQLite and PostgreSQL Alembic histories through `e70b5d2a4c06` | Both passed, including upgrade retry and 66 model-table column checks |
| Real PostgreSQL HTTP/trade/admin authority and commit-order smoke | 12 passed in the independent root verification |
| Native PostgreSQL settlements | Five passed; detailed evidence in the domain results |
| Admin lint, source hygiene and whitespace checks | Passed |

Earlier complete implementation runs also passed AI 19 and Admin 47 tests,
and the Billing/AI/Admin/Landing production builds. These earlier results are
labelled separately from fresh acceptance. Overlapping test runs are not
added together as a unique total. The 23 backend skips include native-database
cases and documented legacy/optional coverage gaps; the Docker-only RLS module
was excluded from the broad SQLite command. Actual PostgreSQL roles are tested
in the separate smoke rather than inferred from SQLite.

Exact commands, durations, failures corrected and scope limits are in
[root-results.json](implementation/root-results.json),
[domain results](implementation/backend-domain-results.json),
[trust results](implementation/trust-sync-results.json), and
[web results](implementation/web-apps-results.json). The original whole-code
inventory and classifications remain in the [30 October file coverage](../2026-10-30/file-coverage.csv).
The [current source manifest](implementation/source-manifest.json) fingerprints
versioned and new source while excluding ignored private data and this generated
report folder.

## Remaining release work

**Immediate external action: rotate the exposed Supabase database password.**
Four tracked diagnostic scripts contained the same embedded credential; it has
been removed from their current source, and importing them no longer connects
to a database. Git history retains the old credential. On 31 October the owner
answered “Not yet / unsure” when asked whether rotation was complete. No live
connection was attempted to test that credential. See [the exposure response](SECURITY-RESPONSE.md).

The supplied log also reports an excess-receipt invoice, multiple open shifts
for two operators and 18 overfilled invoices. These historical discrepancies
remain open pending original receipts, cash counts and a verified private
backup. No financial rows were automatically repaired.

See [the ordered execution plan](PLAN.md): rotate credentials, reconcile the
reported data, validate staging roles/protocol rollout and recovery, test real
phones/printers, then complete the previously planned paid merchant pilot.
Local synthetic checks do not establish product adoption. This report records
the remediation snapshot before publication. The subsequently approved live
schema upgrade, secure Space configuration and publishing targets are recorded
in [DEPLOYMENT.md](DEPLOYMENT.md). No historical financial repair, history rewrite
or live payment was performed by this remediation.
