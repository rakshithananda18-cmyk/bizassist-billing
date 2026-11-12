# Sync scenario and edge-case audit

Date: 12 November 2026. Baseline: d4f63a8 plus the current uncommitted background-sync and Task alignment changes.

The original audit below records the pre-fix findings. The owner subsequently authorized implementation; the working-tree fixes are summarized here. This is not a claim of live deployment or exhaustive fault certification.

## How the normal flow works

1. On a downloaded app, an owner password login uses the local backend; a fresh device authenticates the cloud owner and creates the matching local identity mirror.
2. A cloud-issued credential, matching BizID, owner role and active Pro entitlement are verified before activation. A remembered explicit Local-only preference skips automatic activation.
3. Local + Cloud keeps ordinary business writes in the local database and durable outbox. The worker sends bounded upload chunks, then requests incremental cloud feed pages.
4. The cloud feed uses committed revisions rather than wall-clock timestamps for its cursor. Applied pages advance the cursor; rejected or parent-dependent records should remain in a durable inbox.
5. The initial restore marker stays pending through partial pages and pending inbox rows. Later sessions use incremental updates. The gaps below qualify these guarantees: the current completion test does not account for every failure.

The scheduler actually ticks every 15 seconds, with an ordinary per-business push gate of 30 seconds and a default pull interval of 120 seconds. Initial download and additional pending pages can run on the next scheduler opportunity. These are opportunities, not delivery-time promises: requests, backoff, other businesses, locks and service availability affect timing. Instant Pull uses a cloud event stream when available; periodic pulling remains the fallback. Upload chunks contain 20 changes, the normal worker selects up to 100 pending entries per cycle, and protocol-v2 download pages request at most 1,000 feed events. The local backend must be running for local synchronization to proceed.

## Original audit scenario matrix (before the fixes below)

"Test-backed" means relevant isolated coverage exists, not that a live deployment or every interleaving was exercised. E-numbers refer to findings below.

| Scenario | Current behaviour and practical limit | Assessment |
| --- | --- | --- |
| Existing Pro owner signs in with password | Verified same-business activation starts background work without the old bulk-transfer popup. | Test-backed normal path. |
| Pro owner uses a completely new local device, online | Creates the local identity mirror and starts paged cloud restoration after provisioning. Records arrive progressively. | Test-backed; E04-E06 qualify completeness. |
| Brand-new device is offline | It cannot verify a cloud identity or download previously unseen cloud records. First cloud-linked setup needs connectivity. | Expected limitation. |
| Existing device works offline | Local backend/database can continue supported local work; queued changes wait for cloud connectivity. Browser queue ownership is scoped to the business/operator. | Test-backed ordinary outbox path; disk/browser storage must remain usable. |
| Web app login | Uses cloud data directly; does not create a desktop SQLite mirror. | Code-checked design. |
| Internet fails halfway through a download | Previously committed data/cursor remain; an unread page is retried later. A partial first restore remains pending. | Test-backed; activation must already have a usable credential. |
| Backend exits after applying records but before saving cursor | Replay can occur after restart. Ordinary stable-UID upserts are intended to absorb replay. | Test-backed ordinary identity cases; E01/E02 remain exceptions. |
| More than one download page is needed | The persisted bootstrap marker and next-page state continue the download on scheduler ticks. | Test-backed. |
| Upload succeeds but its HTTP acknowledgment is lost | Queue replay uses durable identities/request IDs; ordinary sequential retry should not create another logical record. | Existing idempotency coverage; true PostgreSQL concurrency still needs testing. |
| Child arrives before its parent | Correctly enriched records are held and retried through the inbox/outbox. A permanently missing parent eventually needs operator attention. | Test-backed dependency handling; legacy raw integer FK is a limitation. |
| Rejected row cannot be durably recorded in the inbox | The caller ignores a failed receipt and can advance the cursor without retaining the row. | Reproduced E05. |
| Journal/payment post-apply invariant fails | The row may land, the failure is logged, and restore can still report complete without a durable repair item. | Reproduced E04. |
| Cloud adds an entity unknown to an older client | The client skips it yet can advance its cursor and mark the restore complete. | Reproduced E06. |
| Cloud is starting, down or returns busy responses | Health/refresh paths have some retry/backoff; sync data requests do not consistently honour their own Retry-After response. | Partial handling; E17. |
| SSE/Instant Pull disconnects | Periodic pulling provides the fallback while the worker, token and plan remain usable. | Code/test-backed fallback, not an immediate delivery guarantee. |
| Initial cloud-token provisioning fails | Ordinary local sign-in can succeed, but a missing credential is not provisioned again on reconnect/session reload. Another password login is needed. | Confirmed E11. |
| Cloud token nears expiry while online | The scheduler attempts renewal; a failed disk write preserves the previous token and backs off. | Existing token tests; E09 qualifies overlapping requests. |
| Device stays offline past token expiry or token is revoked | An expired/rejected cloud token cannot silently authenticate again; online owner reauthentication is required. Local records are retained. | Expected authentication boundary. |
| Old token request completes after a new login | Old 401 can delete the new credential; old successful refresh can overwrite it. | Reproduced E09. |
| Pro expires | Activation rejects inactive Pro. Continuing data sync is gated by configured subscription enforcement and cloud refusal; queues/data are not deleted simply for expiry. | Code-checked; verify production enforcement configuration. |
| Pro is renewed | A refreshed verified subscription can clear the plan halt; a missing/invalid credential still needs separate recovery. | Existing plan refresh coverage; E11 still applies. |
| Wrong BizID, staff cloud token or another owner's credential is supplied | Activation rejects the mismatched/unauthorized identity instead of enabling its mirror. | Test-backed activation boundary. |
| Owner explicitly selects Local-only | Core queued worker, between-upload-chunk and in-flight-download checks respect committed Local-only. Other writers and network paths do not all respect it. | Partial coverage; E07/E08. |
| Local-only is selected during a pending request | Already accepted remote work cannot be recalled. Core download response is discarded after the tested mode recheck; later control/parity/relay work may continue. | Core test-backed; E08. |
| Two tabs save settings while one selects Local-only | Older unrelated settings or subscription responses can overwrite the newer Local-only choice and its revision. | Reproduced E07. |
| Owner switches account while a login/health response is pending | New sync helpers and queue/status readers fence the original session. General session retry has a separate wrong-account logout race. | Test-backed specific fences; reproduced E10. |
| Google login on a new local installation | Does not use the password-login cloud mirror/provisioning flow; an existing cloud Google owner can be offered new local onboarding. | Confirmed E12. |
| Staff uses a fresh remote device | Existing fallback runs against the cloud; it does not create an independent local owner mirror/offline database. | Current design, not owner restore parity. |
| Terminal is configured to use a LAN master | Owner login may use that master, but automatic provisioning/restore targets localhost instead. | Confirmed E13. |
| Recovery endpoint never completes | Some password-recovery, mirror and staff fallback requests have no deadline, so login can remain pending. | Confirmed E14. |
| Several businesses exist in one local database | The remote numeric owner ID can match a different local owner during fallback matching and overwrite that owner's row. | Reproduced critical E01. |
| Two genuinely distinct customers/products share a name | Natural-key fallback can replace an already populated UID and merge distinct records. | Reproduced E02. |
| Two independent offline devices sell stock | They cannot reserve stock against one shared online authority while disconnected. Additionally, merged inventory snapshots can disagree with the merged ledger. | Design limitation plus reproduced E03. |
| Two devices use the same invoice counter/series | Independent local sequences can issue colliding document numbers. Device/counter series must be distinct; sync does not allocate an offline-safe device namespace automatically. | Design limitation; E02 makes a collision more dangerous. |
| Invalid UPDATE arrives alongside valid records | Mutating an existing ORM row before opening its savepoint can abort the batch instead of rejecting only that row. | Reproduced E15. |
| Two devices change the same record | Sequential timestamp-based decisions and financial review logs exist. Equal-time payloads, delete ordering and concurrent PostgreSQL writers have unresolved cases. | E19; concurrency needs live database tests. |
| A cloud row is far ahead of the local clock | Current future-clock guard holds the row in the inbox instead of safely guessing an overwrite. Clock correction/operator retry may be required. | Existing inbox/clock handling; not automatic conflict-free merging. |
| Token file is corrupt, unwritable or replacement fails | Reads fail closed; activation refuses unsafe credential replacement. Atomic writes preserve the previous file on the tested failure. | Test-backed; not protection from an unreadable/corrupt business database. |
| Disk fills or business database becomes corrupt | Some transactions roll back, but no end-to-end power-loss/corruption certification was performed. Failed inbox receipts and false healthy status need correction. | E05/E16; dedicated fault testing required. |
| Multiple backend processes run against one install | Locks/cursor caches are process-local; concurrent token read-modify-write can lose a saved credential. | Reproduced E18; keep to the supported single-worker model. |
| Health says zero pending or a prior manual kickoff failed | Empty outbox is not full reconciliation. Query failures can look empty; an old kickoff failure can remain visible after recovery. | Confirmed E16. |
| Original attachments/import files are expected on another device | Generic sync moves mapped business data, not every original upload; file IDs are deliberately local-only. Derived journal entries are rebuilt rather than copied. | Explicit design boundary, not a full device backup. |

## Findings to fix later

### E01 — Critical: cross-business fallback matching

The pull path uses the source database's numeric business_id to look for a natural-key match in the receiver. It then changes the selected row's business_id to the receiving owner, without first verifying that existing row belongs to that owner. Reproduced: local A=7, cloud A=42, local B=42; pulling A's Rice product overwrote B's Rice product and transferred it to A. This is a business-isolation defect, not merely duplicate UI data. Fix: scope all matching to the verified receiving business, reject foreign-owned existing rows, and assert ownership before modifying any row. [Lookup](<D:/Dev Workspace/bizassist-billing/backend/services/sync_worker.py:2368>), [repinning](<D:/Dev Workspace/bizassist-billing/backend/services/sync_worker.py:2594>).

### E02 — High: distinct UIDs can be merged by name/number

Natural-key fallback can select a row that already has a different nonempty UID. Reproduced: two same-name customer UIDs became one row with the cloud UID. Product names, invoice numbers and some purchase identifiers have related fallback risks; purchase-number matching omits supplier identity. Fix: use stable identity as authoritative; limit legacy adoption to provably unkeyed rows, and quarantine ambiguous matches. [Customer fallback](<D:/Dev Workspace/bizassist-billing/backend/services/sync_worker.py:2411>).

### E03 — High: stock cache does not reconcile merged movements

Reproduced opening +10, device A sale -3 and device B sale -4: the merged ledger summed to 3, but the synced inventory snapshot showed 6. The shared post-apply hooks do not rebuild the affected inventory cache. Fix: derive/reconcile stock from the accepted movement identities as part of successful sync; separately define an explicit offline oversell policy. [Stock truth](<D:/Dev Workspace/bizassist-billing/backend/core/stock/ledger.py:72>), [post-apply hooks](<D:/Dev Workspace/bizassist-billing/backend/core/sync/apply_hooks.py:508>).

### E04 — High: initial restore can finish with failed derived state

A fault-injected post-apply failure still produced a completed cursor, zero inbox, a cleared bootstrap marker and a progress event reporting no failures. Hook failures are collected/logged but not retained as durable repair work; inbox drain also drops the hook_failure result. Manual journal repair exists, but that is not automatic recovery. Financial writes also have no first-restore readiness gate, and the restore banner is hidden on the billing screen. Fix: persist/retry failed invariants, include them in readiness, and define safe financial actions during initial restore. [Failure handling](<D:/Dev Workspace/bizassist-billing/backend/services/sync_worker.py:3580>), [completion](<D:/Dev Workspace/bizassist-billing/backend/services/sync_worker.py:3825>), [billing banner condition](<D:/Dev Workspace/bizassist-billing/frontend-billing/src/layouts/AppLayout.jsx:2911>).

### E05 — High: an unsuccessful inbox receipt is not a reason to hold the cursor

The pull loop ignores inbox.remember returning None. With that failure injected, a declined customer was absent from both tables and inbox while the cursor advanced and restore was marked complete. This is a reproduced failure-contract gap; it is not a claim that every disk-full failure behaves this way. Fix: require a durable receipt or roll back/hold the page before acknowledging it. [Inbox call](<D:/Dev Workspace/bizassist-billing/backend/services/sync_worker.py:3596>), [receipt contract](<D:/Dev Workspace/bizassist-billing/backend/core/sync/inbox.py:123>).

### E06 — High: unknown cloud entities are silently acknowledged

A synthetic protocol-v2 page containing an unknown entity was skipped, not retained, and its cursor was acknowledged with bootstrap complete. A newer cloud/older desktop combination can therefore silently miss a new entity. Fix: negotiate schema capabilities or stop with an update-required state; never acknowledge unsupported data as restored. [Skip](<D:/Dev Workspace/bizassist-billing/backend/services/sync_worker.py:3541>).

### E07 — High: unrelated writers can undo Local-only

Two memory-only reproductions of the actual functions showed local/revision1 being overwritten with hybrid/revision0: one older unrelated settings save, and one subscription response started before the choice. The activation endpoint's comparison-and-set protects its own write, not these other complete-settings writers. Fix: preserve server-owned consent fields atomically for every settings/subscription writer. [Settings write](<D:/Dev Workspace/bizassist-billing/backend/routes/auth.py:1432>), [subscription write](<D:/Dev Workspace/bizassist-billing/backend/routes/auth.py:1232>).

### E08 — High: Local-only is not an application-wide network boundary

Reproduced POS relay sends with a stored token despite Local-only. Source inspection also found telemetry export without a mode gate, control flush checking only before its multi-event loop, parity continuing through pages/repairs after a switch, manual parity without a mode check, and diagnostic archive retries checking only once. Listener shutdown is eventual and does not actively close its blocking stream. Fix: one consistent policy at every egress/repair boundary, per-request consent checks, and an explicit independent policy for diagnostic consent. Already accepted remote requests cannot be recalled. [POS relay](<D:/Dev Workspace/bizassist-billing/backend/services/realtime.py:229>), [control sends](<D:/Dev Workspace/bizassist-billing/backend/services/control_outbox.py:124>), [parity page](<D:/Dev Workspace/bizassist-billing/backend/services/sync_worker.py:1727>), [telemetry export](<D:/Dev Workspace/bizassist-billing/backend/services/telemetry_relay.py:180>).

### E09 — High: stale authentication responses can replace/delete new credentials

Reproduced old refresh401 deleting a newly provisioned credential and old refresh200 overwriting it. Invalidation removes the current token without checking which credential was rejected; listener/push/pull callers share that invalidation. Fix: compare token generation/expected credential atomically before storing a refresh or invalidating. [Invalidation](<D:/Dev Workspace/bizassist-billing/backend/services/sync_worker.py:705>), [refresh result](<D:/Dev Workspace/bizassist-billing/backend/services/sync_worker.py:812>).

### E10 — High: a retry from account A can log out account B

Using actual session/error helpers and synthetic tokens, a 503 retry retained A's Authorization header after switching to B; its marked 401 was treated as rejection of B and dispatched logout. Fix: bind retries and rejection handling to the initiating token/session generation. [Session request](<D:/Dev Workspace/bizassist-billing/frontend-billing/src/api/session.js:53>), [retry](<D:/Dev Workspace/bizassist-billing/frontend-billing/src/api/session.js:82>).

### E11 — Medium: failed first provisioning does not self-recover

If cloud credential acquisition/storage fails when no usable backend token exists, provisioning returns null and activation silently skips. Reconnect, session reload and ordinary token refresh cannot create the missing credential; a fresh password login is required. Fix: an explicit, recoverable setup state and authenticated retry flow, without storing the owner's password. Existing valid-token outages are a separate, normally recoverable case. [Provisioning](<D:/Dev Workspace/bizassist-billing/frontend-billing/src/contexts/AuthContext.jsx:350>), [skip](<D:/Dev Workspace/bizassist-billing/frontend-billing/src/utils/loginSync.js:76>).

### E12 — High product gap: Google/SSO desktop bootstrap

Google login/link/onboarding and some session-creation paths bypass password-login provisioning. A fresh local Google lookup can offer new-store onboarding for an already existing cloud business. Fix: verified cloud identity discovery and safe same-BizID mirroring across supported sign-in methods; do not silently re-key an unrelated local owner. Staff cloud fallback is intentionally a cloud session, not a new offline mirror. [Google session](<D:/Dev Workspace/bizassist-billing/frontend-billing/src/pages/Login.jsx:57>), [backend local lookup](<D:/Dev Workspace/bizassist-billing/backend/routes/auth.py:1708>).

### E13 — Medium: LAN master and localhost restore targets differ

Login can use configured API_BASE on a LAN master while provisioning/verification/activation use LOCAL_URL. Different signing secrets cause rejection; a similarly configured backend can receive work on the wrong service. Fix: capture and verify the actual owning local backend and retain that backend through activation. [Provision target](<D:/Dev Workspace/bizassist-billing/frontend-billing/src/contexts/AuthContext.jsx:370>), [activation target](<D:/Dev Workspace/bizassist-billing/frontend-billing/src/utils/loginSync.js:104>).

### E14 — Medium: recovery requests have unbounded waits

Some cloud-login, local password-reconciliation/mirror and staff fallback calls use bare fetch. A blackholed request can keep login pending before the bounded sync helper runs. Fix: apply one bounded recovery budget and cancellation fence to every recovery request. [Recovery requests](<D:/Dev Workspace/bizassist-billing/frontend-billing/src/contexts/AuthContext.jsx:468>).

### E15 — High: invalid UPDATE can poison its batch

Reproduced an existing stock-ledger update with an invalid required field: the route returned HTTP500 and PendingRollback instead of rejecting only that row. The persistent object is mutated before begin_nested; opening the savepoint flushes it too early. Fix: isolate mutation/flush inside the intended savepoint and retain a durable, visible rejection. [Mutation](<D:/Dev Workspace/bizassist-billing/backend/routes/sync.py:743>), [savepoint](<D:/Dev Workspace/bizassist-billing/backend/routes/sync.py:752>).

### E16 — Medium: misleading health after failures

A failed kickoff remains sticky after successful worker recovery because only pending requests are cleared. Separately, queue/inbox query exceptions fall back to zero rather than unknown/error. Fix: derive status from verified newer outcomes; distinguish unreadable from empty and expose restore, outbox, inbox and invariant readiness separately. [Sticky state](<D:/Dev Workspace/bizassist-billing/frontend-billing/src/layouts/AppLayout.jsx:414>), [queue fallback](<D:/Dev Workspace/bizassist-billing/backend/routes/sync.py:1276>), [inbox fallback](<D:/Dev Workspace/bizassist-billing/backend/routes/sync.py:1305>).

### E17 — Medium: data-request backoff is incomplete

Health and credential refresh understand some Retry-After responses, but ordinary push/pull failures do not consistently schedule response-specific backoff. Initial pending state bypasses ordinary interval gates; repeated failing or held-row restores can poll and log on every scheduler opportunity. Fix: per-business/per-operation retry budgets with jitter, Retry-After and visible next attempt, while preserving durable queues. [Pending bypass](<D:/Dev Workspace/bizassist-billing/backend/services/sync_worker.py:968>), [pull failure](<D:/Dev Workspace/bizassist-billing/backend/services/sync_worker.py:3425>).

### E18 — Medium deployment limitation: multi-process coordination

Separate process namespaces with independent locks reproduced two successful credential saves leaving only one credential. Atomic file replacement prevents truncation, not lost read-modify-write. Worker locks and cursor caches are process-local too. Fix: enforce the supported single-worker deployment or implement durable leases, shared credential storage and appropriate transaction/version coordination. Do not infer duplicate financial effects solely from this token-store reproduction. [Credential write](<D:/Dev Workspace/bizassist-billing/backend/services/sync_worker.py:685>), [worker lock](<D:/Dev Workspace/bizassist-billing/backend/services/sync_worker.py:535>).

### E19 — Unresolved ordering policies and integration tests

Source inspection found nonfinancial deletes occur before timestamp comparison; retained tombstone/version checks are insufficient to prevent stale delete or resurrection. Equal-time differing financial payloads can overwrite without the strictly-newer financial conflict detector firing. Legacy UID-less parent FKs can match a different same-business local integer identity. Sequential last-write-wins is not a merge of two people's intentions, and marking a conflict resolved only acknowledges its review; it does not automatically restore the intended values.

PostgreSQL pushes also read/check versions without a row lock/version comparison at final write; a stale decision between concurrent transactions needs a real concurrent PostgreSQL test. These are source-derived risks/policy gaps, not claimed live PostgreSQL reproductions. Fix: explicit deletion/tombstone, equal-version and legacy identity policies, transaction-level concurrency checks, and PostgreSQL tests. [Delete ordering](<D:/Dev Workspace/bizassist-billing/backend/routes/sync.py:569>), [financial conflict detector](<D:/Dev Workspace/bizassist-billing/backend/core/sync/apply_hooks.py:245>), [legacy FK fallback](<D:/Dev Workspace/bizassist-billing/backend/database/sync_map.py:446>).

## Evidence and remaining validation

- The earlier implementation run passed 197 selected backend tests with 5 PostgreSQL-only checks skipped. That result remains useful evidence for its tested paths; it does not prove every path above is safe.
- This audit ran 31 existing frontend tests across loginSync, deviceModeSwitch, AppLayoutHealth and sessionRejection; all passed. No implementation edits or dependency changes were made for this audit.
- Four isolated real ORM/route reproductions confirmed E01, E02, E03 and E15: [script](<D:/Dev Workspace/bizassist-billing/scratch/sync-edge-audit/reproduce_pull_edges.py>). It asserts observed defects, not desired safe behaviour.
- Three fault-injected bootstrap observations confirmed E04, E05 and E06: [tests](<D:/Dev Workspace/bizassist-billing/scratch/sync-edge-audit/test_bootstrap_edge_observations.py>). All three observation tests passed. A passing observation means the unsafe state was reproduced.
- Six memory-only probes compiled actual function ASTs with substituted dependencies and confirmed two E07 races, POS relay in E08, two E09 races and E18: [script](<D:/Dev Workspace/bizassist-billing/scratch/sync-edge-audit/durability_ast_probes.py>). These establish the algorithmic interleavings, not a production stress-test result.
- One VM reproduction using the actual session/error helpers confirmed E10: [script](<D:/Dev Workspace/bizassist-billing/scratch/sync-edge-audit/reproduce_session_retry.mjs>). All tokens and responses were synthetic.
- Reproducers are ignored scratch artifacts. No production account, installed token store or live cloud data was used. Application implementation files were left unchanged.
- Still required: real PostgreSQL concurrent transactions/RLS, a dedicated cloud business with two local test devices, network interruption at each commit/ack boundary, disk-full/permissions/corruption, long offline expiry, old/new app versions, LAN routing and every sign-in method. Compare invoice/payment/movement identities and sums, not only row counts.

## Recommended fix order

1. Block wrong-business/ambiguous identity updates; reconcile ledger-derived stock; make failed financial invariants/inbox receipts/unsupported entities prevent false restore completion. Define first-restore financial readiness.
2. Preserve Local-only through every writer and egress path; fence credential replacement/invalidation and general session retries to the initiating account/version.
3. Unify verified Google/LAN/password setup, bounded deadlines and missing-credential recovery; repair invalid-row isolation, backoff and status reporting.
4. Enforce or implement the supported multi-worker model; settle deletion/conflict policies and pass real PostgreSQL/two-device acceptance tests before broad rollout.

Original attachments require an explicit backup/asset-sync product decision. Offline stock reservations and document-number namespaces need a deliberate business policy in addition to sync code. These are not solved by making requests retry more often.


## Implementation follow-through — 12 November 2026

The following changes are implemented in the working tree. The earlier scenario matrix and E01–E19 descriptions preserve the original observations; this section supersedes their statements that fixes are deferred.

| Findings | Implemented behavior |
| --- | --- |
| E01–E02 | Receiver-business ownership checks cover direct, child and shared B2B rows. Natural-key UID adoption is limited to unambiguous legacy rows with no existing UID. Different durable identities are never merged by display name. |
| E03 | Accepted stock movements repair their exact inventory bucket from the ledger. Duplicate device cache rows retain their identities and metadata while their combined quantity equals one ledger balance. Legacy snapshot-only stock is retained. Posted movement bucket identity cannot be moved by sync; corrections use new movements. |
| E04–E06 | Failed derived-state hooks produce durable repair-only inbox entries. Repairs use the current row and run under the sync context. Financial writes are blocked during first restore, including a paused restore. Failed receipts roll back the page; unknown entities hold the cursor and require a compatible app. |
| E07–E08 | Settings writes use compare-and-set merges. Explicit Local-only is server-owned and carried in local login claims. Automatic activation cannot undo it. Cloud relays, controls, parity and diagnostics recheck committed consent; diagnostic uploads also need their own opt-in. Already accepted remote work cannot be recalled. |
| E09–E10 | Token file writes are atomic and locked across processes. Refresh/invalidation compare the initiating credential. Browser retries and response bodies are fenced to the originating session, business and backend. |
| E11–E14 | Reload/reconnect first resumes the backend's renewed credential, then can retry scoped browser proof. Missing authorization asks for online sign-in without storing a password. Google and registration use verified cloud-first identity mirroring with collision refusal. Automatic legacy reclaim is refused; a new cloud identity cannot authorize deleting an existing local business. Password reconciliation requires a verified cloud owner for the same BizID. Provisioning retains the LAN master, and recovery deadlines cover response bodies and the overall request budget. |
| E15 | Field mutations occur inside per-row savepoints. Integrity/scalar failures remain reviewable while independent valid rows can commit. Connection failures retry the batch instead of acknowledging unprocessed rows. |
| E16 | Unknown queue/health reads remain unknown. Billing also shows first-restore status; a failed kickoff clears only after a newer successful completion observation. An empty outbox is not proof of a completed first restore. |
| E17–E18 | Durable per-business operation budgets honor Retry-After with exponential backoff. OS locks protect credential/retry read-modify-write and allow only one sync scheduler/listener process per installation. |
| E19 | Versioned tombstones prevent stale resurrection, including raw-SQL local deletes. Strict sync rejects unproven integer parent identities and conflicting equal-version financial edits. PostgreSQL sync decisions take a transaction-scoped business lock, and shared feed ownership/lock order are guarded. Independent installations register distinct cloud-issued namespaces for automatic POS/CN/DN series. |

Schema: `h6_sync_reliability` follows `h5_account_identity_bootstrap`. It adds retained deletion history and device namespaces, refreshes change-feed/security installation, and backfills historical deletes only when the row is still absent. The downgrade deliberately retains deletion protection. Apply the cloud migration and deploy compatible endpoints before rolling out upgraded local clients. Run `python -m alembic upgrade head` from `backend` using the deployment's configured database.

A registered local server shares its namespace and atomic sequence with every LAN browser. A new independent local server registers once while online before hybrid billing. New mirrors copy verified business/profile and billing preferences, while installation identity and consent stay local. A free/Local-only fresh registration is writable only after the cloud attests it has no existing business records; populated businesses retain the restore guard. Historical documents keep their issued number; a new POS draft is scoped before issuance, and the printed receipt uses the server's response. Explicit manually supplied note numbers and historical collisions remain subject to uniqueness checks/review. Do not run two cloned installation data directories with the same installation identity as independent servers; provision a separate installation identity first.

Offline sales cannot reserve globally shared stock while disconnected. These fixes reconcile accepted movement identities; they cannot promise that two disconnected shops never oversell. Physical database loss still requires backups, and uploaded source files are not automatically a full synchronized backup.

### Verification and remaining deployment checks

New behavioral regressions cover tenant/UID isolation, stock/cache consistency, failed repair durability, receipt/cursor failures, shared B2B replay, remote deletes without echo, raw-SQL deletion upload, immutable movement buckets, device setup collision refusal, first-restore financial gating, namespace idempotency, settings races, credential races, actual subprocess token/lease exclusion, operation backoff, Google/LAN provisioning, reconnect and stalled response bodies. See `backend/tests/test_sync_edge_data_safety.py`, `test_sync_reliability_boundaries.py`, `test_sync_consent_credentials.py`, `test_device_cloud_session.py` and the frontend auth/sync/payment regression files.

A fresh disposable SQLite database upgraded through the entire Alembic chain to h6; h6 replay/backfill idempotence was also tested. Live PostgreSQL RLS/concurrent-device execution is still a release check, not a result of mocked or SQLite tests. A dedicated cloud test business and two separate local installations must verify interruption/restart, identities, invoice/line/payment totals, stock movements and inbox/cursor state before production rollout. No production account, database, email delivery or cloud restore was used by this implementation's tests.


### Final implementation validation

The targeted backend suites passed 419 distinct checks, with five opt-in PostgreSQL checks skipped. This is the union of the groups below, not the sum of overlapping reruns:

- API/billing/stock/settings/recovery regression set: 222 passed, five PostgreSQL-only skipped across 19 files (`scratch/syncfix-release-api.log` and `.xml`).
- Restore/readiness/device/migration boundary set: 62 passed across four files (`scratch/syncfix-release-boundaries.log` and `.xml`). The final registration-consent changes were rechecked separately: all 12 device setup tests passed.
- Data isolation and stock cache set: 62 passed across three files (`scratch/syncfix-release-stock.log` and `.xml`), including 34 new edge-data tests; the remaining 28 invoice/stock tests overlap the API set.
- Consent/credential/listener/parity suites: 95 passed across seven files, followed by the expanded consent suite at 21/21. These represent 96 distinct checks.
- Final conflict/savepoint check: 22 passed (`scratch/syncfix-final-conflicts.log`); five conflict tests extend the sets above. Refused row mutations keep their failure evidence without a false overwrite log.

Billing frontend: 220 passed across 12 relevant files (`scratch/syncfix-front-release.log`); the final Local-only registration request/claim was then rechecked with 51/51 auth tests. The production build passed (`scratch/syncfix-final-build.log`). Existing React act warnings and the large bundle warning remain.

The final fresh SQLite Alembic upgrade reached the single `h6_sync_reliability` head, and migration/backfill replay is covered by the device setup tests. `git diff --check` and Python compilation checks passed. No dependencies were added. Nothing was committed, pushed, deployed, or run against production data.
