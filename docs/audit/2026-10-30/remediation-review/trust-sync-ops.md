# Trust/sync remediation verification — 30 October 2026

Reviewed the **current working tree**, including unstaged changes and new files, with HEAD `6c52792`. Original audit baseline: `f5d715c`; the committed containment changes were inspected separately from the subsequent working-tree work. No product code, original audit files, staging state, deployment or live data was changed by this review.

**Result: five original issues fixed and four partially fixed.** The new WP2 suite passes all six tests, but independent tests of the intended behavior expose eight remaining failures. The most serious are a late-commit hole in incremental synchronization and incomplete control-outbox ordering/atomicity/delivery.

| ID | Status | Current result |
|---|---|---|
| TS-01 | **Partial** | Compound cursors drain identical timestamps between upgraded peers; the supported legacy timestamp path still loses tied page tails. |
| TS-02 | **Partial** | Request-start cutoff fixes the original ordinary after-SELECT race; delayed/backdated commits can still fall behind the cursor. |
| TS-03 | **Fixed** | Actual worker decision holds progress whenever a table is unread, including simultaneous rejected rows. |
| TS-04 | **Fixed** | Receiver bumps revocation generation on material changes, clears caches on delete, and does not re-revoke identical retries. Valid receiver requests verified. Local delete delivery remains blocked under TS-05. |
| TS-05 | **Partial** | Persistent outbox exists, but mutation atomicity, ordering, scheduler retry wiring and actual tombstone schema are incomplete. |
| TS-06 | **Partial** | Plan guard now binds its tenant before lookup. Anonymous/bootstrap/public/background constrained-role paths remain unresolved and unverified on real Postgres. |
| TS-07 | **Fixed** | Failed table reads now raise and abort export instead of producing a successful empty table. |
| TS-08 | **Fixed** | Actual desktop probe rejects disconnected/malformed/non-200 responses. |
| TS-09 | **Fixed** | Actual auth import rejects short secrets; two valid imports use the configured key unchanged. |

Status is per original issue, not a declaration that the whole subsystem is production-ready. Detailed machine-readable evidence is in `trust-status.json`.

## Remaining release blockers

### TS-02: the cutoff is a wall-clock boundary, not a committed-change boundary

`backend/routes/sync.py:906` captures request time, line 957 excludes later timestamps, and lines 1106–1108 advance a completed pull to that cutoff. This correctly delivers a row written after a table SELECT when its timestamp is also after the request cutoff. That actual production-path test passes.

The remaining hole is a row that **commits after the pull** but carries an earlier timestamp. Models assign Python timestamps before commit, and `backend/routes/sync.py:464`–496 accepts source timestamps subject to a future-clock check; it does not assign a separate cloud receipt/change sequence. Long transactions, offline uploads and a device clock behind the server can therefore commit rows behind an already acknowledged cursor.

The desired-invariant test inserts a customer only after the first pull completes, with `updated_at` two seconds before that pull's cutoff, then requests the returned compound cursor. The next response is empty. This is a direct test of the current endpoint and actual models, entirely in-memory. It models the visibility condition rather than running a real concurrent Postgres transaction.

**Required:** a durable committed-change feed with explicit visibility/acknowledgment rules, or another protocol that can prove eventual delivery of late commits. Request-start time, compound timestamp/id pagination and fixed overlap windows do not by themselves establish that guarantee. A full parity/resync may recover a skipped row; the ordinary incremental feed does not offer it again.

### TS-01: mixed-version peers still take the lossy timestamp path

`backend/routes/sync.py:960`–1016 implements deterministic `(updated_at, id)` cursors. The upgraded worker consumes the returned opaque cursor at `backend/services/sync_worker.py:3277`–3284. Seven tied rows with a page size of two are delivered correctly in the independent test.

However, `parse_cursor` at `backend/routes/sync.py:835` continues to accept ISO timestamps. The old worker derives its watermark from the newest row timestamp in truncated tables and ignores the new `cursor` field. Against the **new server**, a three-row tie with a page size of two still delivers only `[1,2]`; the next request filters strictly greater than the shared timestamp. This matters for a fleet where desktop clients and cloud servers update independently.

The new worker also retains the old timestamp-watermark fallback when an older server sends no compound cursor (`backend/services/sync_worker.py:3292` onward). There is no explicit protocol/capability/version floor or safe upgrade/rollback rule in this change.

**Required:** retain correctness for supported old peers or enforce a negotiated minimum version before enabling paginated sync, with a recovery path for old stored cursors. New/new behavior is verified; mixed-version correctness is not closed.

### TS-05: persistence has been added, but reliable ordered delivery is incomplete

The new `backend/services/control_outbox.py` and `SyncControlOutbox` model persist payloads, attempts and next-attempt times. The worker calls its flush routine at `backend/services/sync_worker.py:2736`. The existing WP2 test correctly proves that a single manually flushed event can survive a simulated network failure and later complete.

The following conditions still fail:

1. **Local deletions cannot pass the cloud schema.** `backend/core/api/staff.py:295` puts `role:""` in the actual deletion payload, while `backend/routes/sync_staff.py:47` accepts only `cashier` or `supply adder`, even for deleted records. Capturing `delete_staff`'s actual payload and validating it with the actual `StaffPushRequest` raises a Pydantic error. Persisting this payload makes it retry a request that will continue receiving HTTP 422. This mismatch already existed; it remains an uncovered delivery condition, not a regression newly caused by the outbox.
2. **Mutation and replication intent are not atomic.** Staff create/update/delete commit at `backend/core/api/staff.py:226`, line 260 and line 288 before enqueueing. `backend/routes/auth.py:832` likewise commits the profile before calling its push helper. An injected enqueue failure leaves a committed new staff row with no outbox event; the helper logs and returns success. A process crash in the same gap has the same outcome. This preserves the central loss condition from the original finding.
3. **The enqueue helper takes ownership of the caller's transaction.** `backend/services/control_outbox.py:59` calls `db.commit()`. A test changes the owner's name, calls the helper, then rolls back; the name remains changed. This makes the helper unsafe to compose atomically with the caller's command. It should add/flush an event in the same transaction and let the command commit both.
4. **An older retry can overwrite a newer successful value.** Due events are filtered at `backend/services/control_outbox.py:81`, ordered at line 83, and the loop continues after non-401 failures at lines 157–179. An old profile event fails once, a newer event succeeds, and the old event later succeeds after backoff. The observed final cloud name is `old`, replacing `new`. The same ordering permits an earlier staff upsert to follow a later delete and recreate a removed login once tombstones are schema-valid. Event IDs are stored but not sent to, ordered by, or acknowledged by either receiver (`backend/services/control_outbox.py:112`–132).
5. **Control-only pending work can be permanently idle.** `run_hybrid_sync` at `backend/services/sync_worker.py:910` checks only the ordinary `SyncQueue` and whether periodic pull is due. A hybrid business with cloud pull explicitly disabled, no ordinary data work, and a pending control event is skipped. The independent test executes the current scheduler function and confirms it never schedules sync. Therefore the failed one-off daemon delivery has no automatic retry in that configuration.
6. **Old tenant events survive purge/rekey and send using the new identity.** The new `SyncControlOutbox.business_id` at `backend/database/models.py:1011` is a plain integer, and the purge's scoped model list at `backend/services/admin_service.py:1050` omits the table. The proof executes the actual relational purge with `delete_owner=False`, rekeys the retained owner row to a new BizID as reclaim does, and runs the actual flush with a fake newly provisioned token. The observed request sends `OLD TENANT PROFILE` with `Bearer FAKE-NEW-IDENTITY-TOKEN`. Thus an old event can overwrite a recreated account's profile or restore old staff after a purported reset. Only external Field/Chroma purge hooks were mocked; no real namespaces or services were touched. This is a newly introduced outbox lifecycle regression.

Additional code-trace limits, not independently demonstrated end to end:

- `trigger_control_flush` can launch concurrent flush threads, while selection has no claim/lease/serialization; multiple senders can race on the same events. Receiver event versions/deduplication are absent.
- This new backlog is not surfaced by the existing queue-depth/health searches inspected here. A durable record without an actionable pending/failed status is difficult for an owner to recover. No UI status claim was verified.
- No dedicated Alembic migration for the new table was found. Current application startup creates model tables with `create_all`, so this is not proof of a runtime missing-table failure; migration-only deployment/schema parity remains unverified.

**Required:** commit mutation plus event together, validate real tombstones, retry control work independently, serialize or revision-protect updates per identity/entity, send and acknowledge stable event IDs, and clear/quarantine pending events on purge/rekey. Include durable retry state in operations diagnostics. Test restart/reconnect and response-loss retries through the actual endpoints.

### TS-06: only one of the constrained-role session paths was changed

`backend/services/auth.py:421`–423 now sets `db.info["business_id"]` before the plan lookup. A direct test of the actual plan dependency confirms the tenant is set before `effective_plan` executes.

The original broader condition remains: anonymous login (`backend/routes/auth.py:249`), signup, public invoice lookup, scheduled tenant enumeration and other bare service sessions have no explicit narrow bootstrap/global privilege design. `backend/database/db.py:199` still takes the Postgres context only from session information; the user FORCE-RLS policy still requires a tenant. Under a constrained runtime role, an anonymous login cannot first discover its identity through a users query that requires that identity. Merely setting the plan guard's session does not resolve this bootstrap cycle.

No full-app real-Postgres NOSUPERUSER/NOBYPASSRLS gate or runtime-role verification was performed here. The inspected CI still runs application financial/sync suites using `postgres`, while its dedicated constrained-role test models only customers. This remains a **conditional deployment defect**, not a claim that current production is using that role or is failing login.

**Required:** explicit migration/runtime/bootstrap privileges and tenant-aware service factories, then actual full-schema constrained-role tests for login/signup/staff/paid gates/public shares/background jobs and negative cross-tenant access.

## Fixes verified

- **TS-03:** The current condition at `backend/services/sync_worker.py:3586` requires `not _pull_failed_tables` before a rejected-row advance. Executing the actual AST-extracted branch for a 3×3 matrix of rejected-row and unread-table counts advances only when no table is unread. This verifies the production decision rather than a copied helper.
- **TS-04:** `backend/routes/sync_staff.py:111`–116 detects material password/role changes, bumps token version and clears cache. Deletion at line 102 clears cache. The actual receiver test verifies version 0→1, removal of a warmed cache entry, no second bump for an identical retry, and removal/cache invalidation for a schema-valid deletion. The invalid **local** deletion payload is tracked under TS-05, not hidden by this pass. This was not a distributed multi-worker cache test.
- **TS-07:** `_fetch_table` at `backend/routes/data_transfer.py:235`–241 raises on a read failure after attempting rollback. Export catches failures and raises HTTP 500 at line 905. The independent test injects failure inside the actual fetch function; the WP2 test separately verifies the outer export refusal. Consistent snapshots and successful restores are separate verification work, not established here.
- **TS-08:** The actual `probe` function in `desktop/src/backend.js:35`–41 is executed with an in-memory HTTP transport. Four cases pass: disconnected body rejected, healthy body accepted, invalid JSON rejected, HTTP 503 rejected. No Electron install or real socket/server was required.
- **TS-09:** `backend/services/auth.py:20`–24 rejects a configured key shorter than 32 bytes. A real subprocess import with a short key fails with the intended error; two real imports with a valid review-only key confirm it remains equal to its configured value. No developer secrets were loaded or printed.

## Tests and artifacts

| Check | Result | Scope |
|---|---|---|
| User-added `backend/tests/test_wp2_sync_durable.py` | **6 passed**, 1.93 seconds on the recorded repeat | Actual new tests, isolated in-memory data and mocked HTTP. The readiness/secret tests copy predicates; direct production checks above supplement them. |
| Independent `test_trust_behavior.py` | **7 passed, 8 failed**, 8.29 seconds | Failures are desired invariants exposing the remaining conditions listed above, not assertions that the original bugs must still exist. Purge/rekey uses in-memory data and mocked external cleanup hooks. |
| Actual desktop probe transport tests | **4 cases passed** | Current JavaScript body; HTTP transport mocked, no real network. |
| Constrained-role Postgres, live two-server/restart/restore | **Not run** | No claim of deployment verification. |

Recorded files: `trust-behavior-results.txt`, `trust-wp2-results.txt`, `trust-desktop-results.json`, `test_trust_behavior.py`, `trust-desktop-readiness.cjs` and `trust-proof-runner.py`. The runner disables dotenv, external DNS/network and telemetry, points application globals at a distinct scratch test database, and runs these suites with `--noconftest` to avoid unrelated shared application fixtures. Actual model/endpoint proofs use fresh in-memory databases. No TestClient/socketpair escalation was needed for this set.

The work should be described as **substantial remediation with remaining sync/control-plane blockers**, not all nine trust/sync issues closed. Complete TS-02 and TS-05 first, define mixed-version support for TS-01, and establish real constrained-role evidence for TS-06 before treating the original release gates as satisfied.
