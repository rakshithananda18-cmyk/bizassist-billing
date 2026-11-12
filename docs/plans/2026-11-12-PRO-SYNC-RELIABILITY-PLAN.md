# Pro device setup and sync reliability

Date: 12 November 2026

## Product behaviour

Pro on a downloaded local app should normally use Local + Cloud. Ordinary login and reconnect should resume synchronization without asking the owner to choose a direction or press a migration button. A deliberate Local-only choice remains authoritative for that business on that device. A web session reads the cloud directly; it does not need to create a local desktop database.

On a new local device, the owner password-login recovery flow establishes the cloud business identity first. The device creates its local identity mirror, verifies the cloud-issued credential against the same BizID, checks the cloud entitlement, activates Local + Cloud and starts the initial download through the existing sync worker. Subsequent work uses incremental synchronization. Existing local data must never be replaced by another business's data merely because usernames or database IDs match.

## Problems found in the existing login path

- Login reconciliation compared record counts and opened a manual bulk-transfer popup. Equal counts do not establish that records or edits agree.
- The fresh-device path started that comparison before cloud credential provisioning completed. The manual transfer could therefore start without its required cloud-issued token.
- Fresh-device signup created an identity mirror without activating background sync or restoring the business data.
- The manual flush control treated a received HTTP response as success without checking whether the server rejected it. A fixed two-second delay was also treated as completion.
- The scheduler checked the hosting mode, but the immediate worker entry could continue after a switch to Local-only.

These are code-level findings. A production failure still needs its actual server response or diagnostic trace to identify every contributing cause.

## Implementation contract

1. Provision credentials before requesting synchronization. Local and cloud JWTs remain separate. Authentication, expiry and business identity are checked before changing mode or replacing a credential.
2. Use the local server's durable worker for login restoration. Do not run browser-wide export/import as routine synchronization. Keep manual backup and migration tools separate.
3. Activation is owner-only, local-device-only and verified Pro-only. The frontend skips explicit Local-only preferences, offline sessions, cloud-routed sessions and superseded accounts. The worker checks the persisted mode again before network work.
4. Persist mode and entitlement only after credential verification; queue work after the database commit. A failed setup leaves the previous usable state intact.
5. A queued request means accepted, not complete. First restoration remains pending across partial pages and restarts. Continue with the durable cloud cursor; retain deferred/rejected rows for retry or review.
6. Show restoring, queued, offline, authentication required and failed states honestly. An empty upload queue is not proof that the first cloud download is complete.

The implementation also protects the boundaries between these steps. A server-owned storage-choice revision and an atomic settings comparison prevent a delayed activation or restore completion from overwriting a newer Local-only choice in another tab or process. Credentials are written through an atomic replacement; a failed write preserves the previous file and prevents activation. Browser health and queue responses are fenced to the current business and session. An accepted manual request releases its button without waiting for a second status request, and the informational cloud-mode update cannot hold up background activation.

## Companion Task workspace alignment

Task now shares Billing's 600 px phone boundary, floating phone header and icon-only bottom navigation, adaptive building mark and inherited appearance tokens. Tablet and desktop retain their wider workspace layout. Owner navigation, staff navigation, search, form overlays, record spacing and narrow-screen action rows were checked using synthetic data. The Billing return link now targets app.staterbill.com and retains business context; lookalike origins remain rejected.

The user's existing Task page and record changes were retained. UI verification covered owner and staff screens at 320/390 px and 768 px, light and dark inherited themes, scrolling, drawer/search focus and modal layering. No production account or field record was modified for these checks.

## Operating rules

- Keep writes in the existing durable outbox until acknowledged. Retrying an interrupted operation must reuse its identity and must not create another invoice, payment or stock movement.
- Apply related records in dependency order. Save cursors only after the associated local transaction commits. An unread page or a deferred parent must not be mistaken for missing data.
- Retry transient network failures with bounded delays and the existing worker's backoff. Authentication, entitlement and identity errors need a distinct halted state rather than repeated uncontrolled requests.
- Keep server-issued ordering and the existing conflict mechanism. Do not introduce timestamp-only last-write-wins for balances, inventory or financial documents.
- Preserve Local-only choice on login, reconnect, upgrade, refresh and account switch. Scope device preferences and credentials to the current business.

## Verification and release

The regression set should cover existing and fresh devices; Pro, expired and local-only accounts; wrong BizID; cloud and local token separation; a failed activation; logout or account switch during verification; a switch to Local-only before worker execution; interrupted first pull; multiple download pages; pending inbox records; rejected manual kickoff; and restart/reconnect continuation.

Before deploying, run a controlled end-to-end test with a dedicated cloud test business and two local test devices. Compare invoice identities, line items, payment totals, stock movements and cursor/inbox status. Row counts alone are insufficient. Interrupt the network and restart a device mid-restore, then confirm it resumes without duplicates. This local code review does not substitute for that deployment check.

The later patch implements inline setup/reauthentication states and first-restore financial readiness. Further work can include a dedicated device-setup screen, device revocation, and operational alerts for an old pending outbox, stuck inbox or repeatedly failing restore. These are separate acceptance criteria; do not label them complete merely because a job was queued.

Original audit gap, now addressed by the verified cloud-first device bridge: the earlier Login setSession path did not obtain and provision the cloud-issued credential used by this password-login recovery flow. The later hardening patch adds verified identity mirroring and bootstrap for this path, with regression coverage. A local-only Google account must not be silently re-keyed to another BizID.

## Local validation results

A subsequent [scenario/edge-case audit](<D:/Dev Workspace/bizassist-billing/docs/plans/2026-11-12-SYNC-EDGE-CASE-AUDIT.md>) found additional defects outside the original tests, including cross-business fallback matching, ambiguous UID adoption, stock reconciliation, false restore completion, complete-settings writers undoing Local-only, and cloud traffic through auxiliary paths. The implementation contract above describes the intended behaviour; it is not a blanket guarantee that the whole application already satisfies it. The owner subsequently authorized the fixes; the audit now includes an implementation follow-through and deployment checks. The original validation figures below are the earlier baseline, not the result for the later hardening patch.

- Task: 118 tests passed across 26 files; production build passed. The browser checks used the actual app components with an ignored synthetic fixture.
- Billing: 99 relevant tests passed across 8 files, including login/provision sequencing, hosting choices, stale-session responses, request timeouts, slow status reads, preflight, outbox and halt messages. Production build passed. Existing React test act warnings and the build's large-chunk warning remain visible.
- Backend: 197 tests passed and 5 PostgreSQL-only tests skipped across 15 files. Coverage includes verified bootstrap, credential persistence/refresh, protocol v2, pull pagination, inbox/deferred records, idempotency, halt state, mode gates, subscription refresh and scheduler backoff. The final suite used disposable SQLite, mocked cloud responses or a disabled loopback endpoint, and disabled email delivery; no production database or live cloud restore was used. The FastAPI test client needed execution outside the Windows sandbox because its internal socket pair was blocked there.
- Both frontend production builds and git diff --check passed. No dependencies were added. Changes remain in the working tree; no commit, push or deployment was performed.

## References

Microsoft documents automatic initial offline download, subsequent delta synchronization and visible progress/error states in [Power Apps offline behaviour](https://learn.microsoft.com/en-us/power-apps/mobile/canvas-mobile-offline-working). This is a useful reference for the proposed product flow.

[Stripe's idempotent request contract](https://docs.stripe.com/api/idempotent_requests) illustrates safe retries without repeating a successful operation. STATER should retain that property through its existing durable record identities and outbox acknowledgements, rather than copying a billing provider's HTTP implementation verbatim.


## Authorized hardening follow-through

The E01–E19 fixes are now implemented in the working tree. See the audit's implementation and final validation sections for the current behavior, migration and checked scenarios. The later patch includes verified Google/password/registration mirroring, backend-credential resume, installation-scoped numbering, first-restore financial gating, durable repairs and delete history, consent/credential concurrency guards, stock projection repair and accurate status. The legacy automatic reclaim endpoint now refuses replacement of a different local identity.

This patch requires Alembic `h6_sync_reliability` on the cloud, followed by compatible backend/client rollout. A fresh disposable SQLite upgrade and the targeted regression suites passed. PostgreSQL-only and live two-installation interruption/restart checks remain deployment acceptance work. No production deployment was performed.
