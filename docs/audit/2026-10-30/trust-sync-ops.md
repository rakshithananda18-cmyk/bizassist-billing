# Trust, sync, persistence and operations audit — 30 October 2026

Audit baseline: working tree based on `f90ea1f` (30 October 2026). Review date uses Asia/Kolkata. Product code and live data were not changed. This report is an input to the repository-wide audit, not a production security certification.

## Outcome

The highest-priority missing capability in this area is **a durable, transactionally consistent change feed with tested recovery guarantees**. The prior realtime plan already proposed it. Current timestamp-based replication can permanently miss rows under ordinary pagination and concurrent writes. Four current defects were reproduced offline using the actual selected production function bodies; they are not copied hypothetical algorithms.

There is substantial existing defensive work: UID-based identity, child-parent resolution, explicit owner-only sync authorization, an inbox/outbox, savepoints, financial conflict records, transaction-local tenant context, and fail-closed RLS policy predicates. The findings below concern remaining holes between those mechanisms.

## Coverage and verification boundaries

`trust-sync-ops-coverage.csv` inventories 195 assigned tracked files: 49 received manual tracing of selected critical flows in addition to complete-file automated screening, 143 received automated screening, and three binary assets were inventoried/excluded. Automated screening reads the complete text, parses Python AST/JSON where applicable, and indexes risk markers; it does **not** prove every line correct. No Python parse error was found in this assigned set. Lockfiles were inventoried; no vulnerability-advisory scan was performed.

Scope: backend auth/security/session and plan guards; database engine, sync hooks/map, startup migrations and all 42 Alembic revisions; sync push/pull/transfer/staff/profile and realtime infrastructure; related tests and repair scripts; desktop shell/packaging; backup operations and Dockerfiles. Backend domain/accounting/AI semantics and web applications have separate agent reports. CI workflow references here are cross-checks; the parent audit owns workflow-wide coverage.

No production/cloud database, real user account, external service, live restore, deployment, printer, installer, or multi-device session was exercised. Live Postgres RLS behavior was **not** established by this audit.

## Confirmed issues

### TS-01 — P1 — Timestamp ties at a pull page boundary permanently omit rows

Evidence: `backend/routes/sync.py:910` filters with `updated_at > last_sync_dt`; line 932 sorts only by `updated_at`. `backend/services/sync_worker.py:3283` computes the next global watermark from the maximum timestamp in each truncated table and uses its minimum across tables.

With three customer rows sharing timestamp T and a limit of two, the first response returns two rows and `has_more=true`. The worker advances to T. The next request asks for timestamps strictly greater than T and never returns the third row. Imports, backfills and multirow operations can assign equal timestamps; UID uniqueness does not prevent this.

Reproduction: `trust-sync-repros.py`, case `timestamp_boundary_data_loss`. Observed first IDs `[1,2]`, next changes `{}`, omitted ID `3`.

Fix: use a durable change cursor with well-defined visibility/commit semantics. For an interim timestamp protocol, use per-table lexicographic cursors such as `(updated_at, uid)` and a deterministic secondary ordering; a timestamp alone cannot represent progress through a tie. Simply subtracting time can instead livelock when a tie exceeds the page size.

Acceptance: more than a page of identical timestamps arrives exactly once logically, without omission or unbounded repeat, across restart and multiple tables.

### TS-02 — P1 — Response-end watermarks skip writes committed during a pull

Evidence: `backend/routes/sync.py:874` iterates and materializes tables separately; `backend/routes/sync.py:1019` sets `pulled_at` using the time after those reads. A nontruncated successful response advances the worker cursor to that value at `backend/services/sync_worker.py:3614`.

A table is read at T1. Another request commits a change to that table at T2. The pull finishes at T3 and returns T3 as its cursor. The write was not in the materialized table and is older than T3, so the next pull excludes it. This affects both inserted and updated rows and is independent of page ties.

Reproduction: `trust-sync-repros.py`, case `response_end_cursor_race`. It injects a committed write after a table's rows are materialized, during serialization, modeling the same visibility window as a concurrent writer. ID `4` is absent from both the first response and the next incremental response.

Fix: define an actual snapshot/change-feed boundary and acknowledge only what it includes. A request-start cutoff plus overlapping replay is an interim mitigation, not a complete solution for precommit timestamps and long transactions. A sequence allocated before commit also needs visibility/commit ordering safeguards; do not merely replace the timestamp with an unchecked BIGSERIAL watermark.

Acceptance: insert/update each entity between its SELECT and response construction, and hold a transaction open across pulls; every committed mutation must eventually be delivered.

### TS-03 — P1 — A rejected row overrides the safeguard for an unread table

Evidence: `backend/services/sync_worker.py:3578` first handles `_failed_now`; line 3586 advances the cursor. Only the `elif` at line 3587 checks `_pull_failed_tables` and holds it.

When one received row is rejected **and** the cloud reports an unread table, the first branch wins. The rejected row can be preserved in the inbox, but rows from the unread table were never received and cannot be there. Advancing the cursor can skip that table's outstanding records permanently.

Reproduction: `trust-sync-repros.py`, case `partial_pull_plus_rejected_row_advances`. The AST-extracted current decision branch calls `_set_pull_cursor` with both failure conditions present.

Existing `backend/tests/test_pull_partial.py` passes all ten tests. Its source checks inspect the isolated `elif` branch, and its `should_advance_cursor` helper describes an older algorithm rather than executing the current worker decision. Thus a green result here does not cover this combination.

Fix: check unread tables before any cursor advance and test the actual production decision for the cross-product of partial tables, rejected rows, deferred rows, pagination and clean batches.

Acceptance: any nonempty `failed_tables` holds progress for the affected feed, irrespective of received-row outcomes; repair/retry later retrieves the missing rows.

### TS-04 — P1 — Replicated staff password/role changes do not revoke cloud sessions

Evidence: local `backend/core/api/staff.py:259` calls `bump_token_version`, but the receiving `backend/routes/sync_staff.py:104` and line 105 overwrite the password and role without changing `token_version` or clearing its cache. The replication schema does not carry a revocation generation. Deletion at line 97 also omits cloud cache invalidation.

After a local owner resets a hybrid staff member's password or changes their role, successful cloud replication still leaves the old cloud JWT's `tv` valid. Its old role claim remains authoritative until JWT expiration (default 24 hours). Cloud deletion can continue to accept a warmed token-version cache entry for its 30-second TTL.

Reproduction: `trust-sync-repros.py`, case `staff_replication_missing_revocation`. Running the actual `sync_staff_push` function against an in-memory staff row changes its password and role while leaving `token_version=0`, matching the old token claim.

Fix: bump the cloud row's version and invalidate its cache when credentials/role materially change; clear cache before cloud deletion. Make repeated identical replication idempotent so retries do not repeatedly revoke new sessions. A source-issued revocation event/version can help, but local/cloud counters must not be blindly assumed interchangeable.

Acceptance: warm an actual cloud staff session, change password/role from local, deliver replication, and require the old session to fail immediately. Also cover delete and a duplicated push.

### TS-05 — P1 — Staff/profile replication has no durable retry when delivery fails

Evidence: `backend/core/api/staff.py:61` sends staff mutations via a one-off daemon thread; missing tokens return at line 83, HTTP failures log, and exceptions log at line 98. `backend/services/immediate_sync.py:60` does the same for profile fields, returning on missing tokens at line 82 and only logging failure at line 97. `backend/database/sync_map.py:29` intentionally excludes `users` from generic replication. Repository search found no periodic caller that replays these staff/profile mutations.

A hybrid owner can delete a cashier or reset their password while the cloud is unreachable and receive local success. The failed request is not durable and the regular data-sync queue cannot replay it. The old cloud account/credentials can remain usable after connectivity returns until another explicit matching operation or transfer happens. Profile updates such as GSTIN/address/UPI can similarly remain stale on cloud-generated documents.

Verification: complete caller search plus traced failure branches; no live network outage was induced. This is separate from TS-04, which occurs even when delivery succeeds.

Fix: a dedicated encrypted/appropriately protected control-plane outbox with deletion tombstones, durable event IDs, retry/backoff, acknowledgment and visible pending/failed status. Do not restore whole-user rows to generic business-data sync.

Acceptance: create/change/delete staff and save profile offline, restart the app, reconnect, and observe cloud convergence and revocation without another user edit.

### TS-06 — P1, conditional deployment defect — Full-app auth/plan flows cannot operate under the documented constrained RLS role

Evidence: `backend/alembic/versions/9c2f4b8a1d3e_fail_closed_rls_policies.py:53` restricts users to the current business context. `backend/database/db.py:199` takes that context from `session.info`, and `get_db` populates it only if a signed request supplies one at line 226. Anonymous `backend/routes/auth.py:249` looks up a username with no context; signup at line 497 also starts with none. `backend/services/auth.py:418` opens a separate bare `SessionLocal` for the plan guard and never binds the tenant. Its row lookup can therefore see no owner and classify a paying user as free.

Under a NOBYPASSRLS runtime role with the declared users policy, ordinary login sees no account, signup has no permitted tenant identity, and the plan guard can block paid features. Some privileged flows and scheduled services need an explicit, narrow bootstrap/global-access design. Running as a superuser/BYPASSRLS can mask the symptom but removes the claimed RLS protection.

Evidence limitation: this is a direct conditional code/policy trace, not a claim that the current production role is constrained, nor a newly observed production incident. No live role credentials were inspected.

Test gap: `backend/tests/test_rls_postgres.py:13` explicitly tests a tiny customers table rather than the application schema. `.github/workflows/ci.yml:74` and line 113 run application financial/sync suites as `postgres`. Those checks do not establish that login, signup, plan gating, public share links, background jobs and staff-owner joins work with FORCE RLS under a constrained app role.

Fix: define separate migration/runtime privileges, narrowly scoped authentication/bootstrap functions, and tenant-aware session factories for request and service jobs. Add a full-schema app-role integration gate and inspect the deployed role's `rolsuper`/`rolbypassrls` properties through a safe operational check.

Acceptance: real Postgres, actual migrations, NOSUPERUSER NOBYPASSRLS app role; login/signup/paid owner/staff/public-share/background flows work while negative tenant reads/writes fail. Record results, not only policy source strings.

### TS-07 — P2 — A table-read failure is exported as a successful empty table

Evidence: `backend/routes/data_transfer.py:189` fetches an export table. Its exception handler at line 236 returns `[]`, and `export_data` at line 882 accepts it as normal data. The exported object has no `failed_tables` distinction. Unlike the hardened generic sync pull, this handler does not roll back an aborted PostgreSQL transaction before later reads.

A permissions, timeout or database-query failure can produce an incomplete downloaded backup that looks like a valid export. On Postgres a failed statement can also cause subsequent reads to fail in the same transaction, increasing the omitted portion. Table emptiness and unreadability become indistinguishable.

Verification: traced export error/return paths; no real backup was corrupted or restored.

Fix: fail the export atomically on any required-table read failure, or return an explicit incomplete manifest that the UI refuses to label a backup. Include table counts/schema versions and integrity validation; use a database-consistent snapshot.

Acceptance: inject a failed table read and verify no successful backup download is offered. Follow with an export/restore roundtrip and financial/stock reconciliation.

### TS-08 — P2 — Desktop readiness accepts the backend's disconnected-database response

Evidence: `backend/main_groq.py:427` documents that `/health` always returns HTTP 200; line 483 returns `{status:"error",db:"disconnected"}` on DB failure. `desktop/src/backend.js:33` accepts only the HTTP status and treats any 200 as ready (and as an existing backend to reuse).

The shell can open the billing UI despite a failed database and miss its intended startup failure/diagnostic path.

Fix: split liveness/readiness or have the desktop parse `status`/`db`/application identity. Use readiness, not mere process liveness, for checkout availability.

Acceptance: a stub returning HTTP 200 with `db:"disconnected"` fails readiness; a healthy BizAssist response passes.

### TS-09 — P2, configuration-specific — Short JWT secrets become a different signing key per process/restart

Evidence: `backend/services/auth.py:19` tolerates a short configured secret and appends random `token_hex(16)` at line 24 instead of rejecting it.

The same configured short secret produces different effective keys on every restart/process. Old sessions fail after restart; services sharing that configured value cannot verify each other's tokens. The generated desktop secret is long, so that path is not affected.

Fix: reject insufficient secret length at startup with a clear configuration error. Do not silently transform deployment identity with fresh randomness.

Acceptance: an invalid short secret fails startup predictably; a valid configured secret produces stable cross-process verification.

## Important gaps against the previous plans

| Prior commitment | Current evidence | What remains |
|---|---|---|
| Realtime robustness plan §5 Phase 2: same-transaction ordered change log, resume/gap recovery | `docs/plans/REALTIME_SYNC_ROBUSTNESS_PLAN.md`; no `sync_changes` implementation; cloud pull still uses timestamps | A tested change-feed protocol with correct snapshot/commit visibility, per-feed acknowledgments, tombstones and catch-up. This directly addresses TS-01–03. |
| Realtime plan Phase 3: version/optimistic concurrency | `backend/routes/sync.py` and `services/sync_worker.py` retain row-wide timestamp LWW plus conflict logging | Conflict records preserve evidence but do not prevent overwriting a concurrent independent edit. Introduce deliberate per-entity version/merge rules; keep deterministic money commands. |
| Ecosystem plan §6.2: encrypt local SQLite and backups | `backend/database/db.py:29` and line 77 open ordinary SQLite. There is no SQLCipher/key setup there. `backend/server_entry.py` DPAPI-wraps the JWT signing secret only. `frontend-billing/src/utils/backupFile.js:15`–30 downloads JSON and constructs a plain `application/json` Blob. | The SQLite price/customer book and exported JSON are not encrypted by these paths. Decide key recovery/custody using `docs/DECISION_LOCAL_DB_ENCRYPTION_2026-08-03.md`, then implement atomic migration and recoverable encrypted backups. Do not equate secret/token wrapping with database encryption. |
| Ecosystem plan §15 rule 25a: staged, signed, reversible updates and canary halt | `desktop/src/updater.js:23` silently downloads and enables install on quit; line 46 installs immediately on restart choice. `.github/workflows/release.yml` makes signing optional/commented; no required canary/rollback gate is wired into this shell. | Require verified signing and version compatibility, a rollout ring, preserved preupgrade data and a rehearsed downgrade/forward recovery policy. This audit did not inspect released installer signatures; it does not assert every published artifact is unsigned. |
| Ecosystem plan §16.4: rehearsed restores and separate backup keys | `ops/db-backup/backup.py:89` lists the dump's catalog and checks five core table-data entries before upload; README documents a manual restore | Catalog readability is not a successful restore. No actual restore drill evidence was established here. Restore to disposable Postgres, migrate, reconcile all billing/field tables, test login/RLS, and record RPO/RTO. The backup code does not add application-level encryption/separate keys; cloud storage encryption/IAM was not inspected live. |
| D1/D9: one business scope plus stable BizID across local/cloud | Owner-only guards and UID remapping are present, including `resolve_business_id_in_db` | Verify the entire identity/RLS path under the actual constrained role and differing local/cloud numeric IDs; isolated policy tests are insufficient (TS-06). |

Existing master/release documents are appropriately cautious about live verification: `docs/release/2026-10-28-verification.md` says that live two-server reconnect/mode switching, real RLS and full backup restore were not established. Those statements remain limits, not proof that the features are broken. Historical fixture counts or historical known-issue appendices should not be promoted to today's defects without tracing the current implementation.

## Prioritized execution plan for this area

1. **Contain present losses and revocation gaps.** Fix TS-03 and TS-04 first; add behavior tests on the production paths. Fix TS-01/02 with a reviewed protocol change rather than another timestamp heuristic. Add a durable staff/profile outbox and revocation acknowledgments (TS-05).
2. **Establish deployment truth.** Build a full-schema Postgres constrained-role integration environment, implement the missing bootstrap/session boundaries, and record the actual app-role properties and negative tenant tests (TS-06). Keep migration and runtime credentials separate.
3. **Make backup/restore a demonstrated capability.** Fail incomplete export, validate a consistent snapshot, restore one cloud dump and one local export into disposable databases, reconcile money/stock/field collections, measure recovery time, and retain the dated evidence (TS-07).
4. **Close local custody and release safety.** Resolve the existing encryption decision, migrate local SQLite safely, protect exported backups with recoverable separate keys, enforce signed release artifacts and rehearse update rollback/forward recovery. Fix readiness/short-secret behavior (TS-08/09).
5. **Only then broaden realtime/product scope.** Add durable ordered replay/optimistic concurrency to remaining entities and a two-device soak. Presence, extra notification polish and new network/AI features should follow the integrity gates.

Release gates: repeated identical timestamps; concurrent insert/update during pull; unread-table plus rejected-row combinations; offline staff deletion/reset through restart/reconnect; local/cloud ID mismatch; constrained-role full-app isolation; export failure; restore reconciliation; version skew and interrupted update; 24-hour multi-device soak with no missing durable mutations.

## Verification performed

| Check | Result | Meaning/limit |
|---|---|---|
| `trust-sync-repros.py` | Four reproduced defects; process exit 0 after all assertions | AST-extracted current function bodies, in-memory SQLite, no app startup or network. JSON results retained beside this report. |
| Existing `backend/tests/test_pull_partial.py`, with `--noconftest` | 10 passed in 0.20 seconds | Tests retain their existing bodies; disabling conftest avoids unrelated application fixtures. Their pass does not contradict TS-03 because they do not execute that combination in the production branch. |
| Existing `ops/db-backup/test_backup.py` | 8 passed in 0.09 seconds | Mocked/unit dump/URL/catalog checks only; no real pg_dump/cloud storage/restore. Initial sandbox temp-directory failures were resolved by pointing the runner's temporary directory inside the workspace; no product change. |
| Static Alembic revision graph | 42 revisions; one head `f7b8c9d0e1f2`; no missing parent | This establishes graph shape, not successful fresh/existing Postgres/SQLite migration. |
| Assigned source AST screening | No Python parse errors | Does not establish imports, authorization or runtime behavior. |
| Nine-module trust/sync integration attempt | Interrupted after progress; no completed summary | No suite pass claim. The app-fixture attempt made no further visible progress and was stopped; root DBs and external services were not used. |

Artifacts: `trust-sync-repros.py`, `trust-sync-repros-results.json`, `trust-test-runner.py`, `trust-static-test-results.txt`, `trust-backup-test-results.txt`, `trust-coverage-inventory.py`, and `trust-sync-ops-coverage.csv`. The guarded runner forces a scratch test database, disables dotenv/telemetry and blocks external network/DNS. No tests against live business data were authorized or performed.
