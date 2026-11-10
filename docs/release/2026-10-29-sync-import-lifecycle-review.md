# Billing import, sync and account lifecycle review — 29 October 2026

## Scope and changes

Reviewed the supplied cloud startup/import/deletion logs, the mounted transfer API,
manual migration/backup callers, registration, and the existing account lifecycle plan.
The two local databases remain separate. Billing and Field Team share the online
business identity; Field Team remains Pro gated and cloud only.

- B2B restore compares durable line UIDs, then a float-tolerant multiset of financial
  fields. Identical legitimate lines keep their multiplicity. Orders and products
  must resolve within the verified business pair/seller catalogue.
- Existing B2B status, consent and balances are not reverted by a backup import.
  Conflicting totals, UID reuse or missing products reject the whole import with
  HTTP 409. Newly restored orders must have complete, reconciling lines.
- SQLite now explicitly starts the outer import transaction before any SAVEPOINT.
  A regression demonstrated that releasing a first savepoint could otherwise commit
  an early row even when the final import rolled back. PostgreSQL still uses its
  normal transaction semantics. Database overfill guards stay enabled.
- Generic skipped records are returned explicitly. Rejected financial records
  roll back the entire import. Manual sync, file restore and hosting migration
  inspect partial results; they no longer report complete success or stamp a
  successful sync for an incomplete import. Missing validation counts fail the
  migration check. Hosting preferences must save before the client switches API.
- Admin deletion detaches optional catalogue references from surviving historical
  invoices, purchase lines and named stock snapshots. Their quantities, prices and
  totals remain intact. Required references from another business block the purge
  with HTTP 409 before deleting any records.
- Docker downloads the embedding model as the runtime user, avoiding a root-owned
  Hugging Face cache. This needs a fresh image build/deployment to take effect.
- Registration offers Local only and Local + Cloud. On a public web origin Local
  only is disabled, with a small desktop download link. Browser signup still uses
  the cloud backend; the same account can add Local billing in the desktop app.
  Automatic Local + Cloud sync requires Pro or an eligible trial.
- Registration uses safe scrolling when the card is taller than the viewport.
  The mobile showcase panel no longer overrides the responsive hide rule.
- The database audit compatibility helper recognises SQLAlchemy's underlying
  PostgreSQL driver instead of issuing SQLite metadata SQL through a pool proxy.

## Cloud deletion versus local copies

The completed items in `docs/archive/MASTER_REVIEW.md` describe **account lifecycle
tombstones and guarded reclaim**, not a deployed remote wipe protocol:

1. Cloud admin wipe purges that cloud business and records its retired BizID in
   `deleted_businesses`.
2. Cloud authentication/sync refuses the deleted account; a 401 stops/invalidate
   credentials, but is not treated as proof of account deletion.
3. If an owner re-registers in the cloud, a verified identity mismatch can use the
   existing local reclaim path. Reclaim purges stale local data/staff before
   rekeying the retained owner row to the newly verified cloud BizID.
4. Local devices do **not** consume `deleted_businesses` and do **not** automatically
   erase their offline copy when the cloud admin deletes an account. An offline
   device could not react until it reconnects in any case.

The missing delete channel is also recorded in the August platform ledger §4.4.
Do not label account tombstones as row-delete propagation or claim that every local
copy has been erased. General row tombstones, repair-deletion convergence and an
account retirement acknowledgement protocol remain pending.

Recommended next lifecycle design: a cloud-authenticated, retired-BizID signal;
pause cloud sync without discarding the outbox; show the owner an account-retired
state; provide backup/export before explicit local cleanup; record per-device
acknowledgements. A transient 401, expired session, outage or a reused username must
never erase local billing records. A deliberate remote wipe policy needs an explicit
product decision distinct from cloud-account deletion.

## Existing data findings and operational work

The supplied logs report historical overpaid receipts, duplicate open shifts,
overfilled documents and legacy staff BizIDs. These are data reconciliation work,
not proof that a startup repair should guess or overwrite amounts. No live financial
repair, shift closure, import or business deletion was performed in this review.
Review the correct database backup, receipt ledger and actual counted cash before
applying a targeted repair. Preserve a before/after money snapshot. Keep identifying
business data and logs out of public fixtures.

Deployment follow-up: rebuild the Space image, deploy the Billing frontend, then
exercise a two-server offline/reconnect cycle with disposable accounts and verify
the results by document UID and totals. A passing isolated suite does not prove
production parity or physical printing. The live subscription enforcement flag
must be checked separately; this change does not alter entitlement policy.

## Verification

Named backend suites: `test_b2b_import_conflicts.py`, `test_b2b_transfer.py`,
`test_b2b_transfer_internals.py`, `test_admin_purge_product_refs.py`,
`test_data_transfer.py`, `test_sync_migration_fixes.py`,
`test_data_transfer_staff_identity.py`, `test_line_item_invariant.py`,
`test_push_trigger_guard.py`; local-only lifecycle: `test_reclaim_local.py`.

Named frontend regressions: `HostingComponents.test.jsx`, `BackupModalLegs.test.jsx`,
`FileBackupCard.test.jsx`, `RegisterCloudStorage.test.jsx`.

Completed checks (runs overlap; do not sum these as unique test counts):

| Check | Result |
|---|---|
| Billing frontend full suite | 844 passed / 106 files |
| Final affected Billing frontend regressions | 42 passed / 4 files, after the final error/animation cleanup |
| Admin frontend full suite | 47 passed / 3 files |
| Billing and Admin production builds | Both passed; Billing retains a bundle-size warning |
| SQLite core import/purge/reclaim/invariant/SQL-portability set | 252 passed, 10 skipped |
| SQLite desktop sync audit set | 119 passed |
| Final import-conflict set, including the two added generic skip cases | SQLite: 11 passed, 1 PostgreSQL-only trigger test skipped; PostgreSQL: 12 passed |
| PostgreSQL core import/purge/invariant/sync guard set | 95 passed |
| PostgreSQL wider sync and SQL-portability set | 266 passed, 9 skipped, 8 desktop-only tests deselected |

Nine SQL-portability skips are explicit exceptions for scripts documented as
SQLite-only. The extra SQLite skip is the real PostgreSQL trigger-abort regression,
which passed on PostgreSQL. The eight deselected cloud-run cases assert SQLite
desktop queue/worker/subscription-refresh behavior; all passed in the SQLite run.
An earlier Windows diagnostic timer caused a native test-process crash during
teardown; the final SQLite run passed after removing that scratch-runner timer.

Backend tests used guarded, disposable databases with external network blocked;
the PostgreSQL server was a workspace test cluster on loopback. No production or
developer business database was used for fixtures or repairs. The Docker image
was not built here because Docker is unavailable; the model-cache fix still needs
an actual Space rebuild and startup verification.

Browser evidence: the in-app browser checked registration at the normal desktop
viewport and 390 × 844. A loopback development alias exercised public-web routing:
Local only disabled, a separate download link, Local + Cloud selected, no standalone
Cloud card. The corrected mobile panel fills the available height, has no horizontal
overflow, and scrolls to the submit button. No registration was submitted. The
localhost desktop branch retains its enabled Local choice.

This is a scoped Billing/sync review, not a claim that the entire backend suite,
live production parity, physical checkout printing or every authenticated Billing
page was retested. Existing Field Team work in the shared checkout was preserved.
Changes are prepared locally; this review did not publish a new Git/Hugging Face
deployment.
