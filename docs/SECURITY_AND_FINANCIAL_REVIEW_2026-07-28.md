# Security, Tenant Isolation, and Financial Integrity Review — 2026-07-28

## Release position

**Do not release a public multi-tenant cloud deployment until the verification gates below pass.**

This review covers the billing frontend, backend authentication and APIs, stock
and billing commands, imports, offline browser sync, and local/cloud sync.
The changes in this release close the highest-confidence P0 paths found in the
source review. They do not replace staging verification against the production
database role and actual packaged desktop runtime.

## P0 remediations implemented

| Area | Change | Security/integrity effect |
|---|---|---|
| Local account recovery | Password reconciliation and local-account reclaim now reject cloud and LAN callers; the packaged desktop backend binds to loopback. | A public BizID cannot be used against a cloud recovery endpoint. |
| Control-plane authorization | `require_business_owner` requires both the owner business ID and the same authenticated user ID. It protects cloud-token storage, generic push, staff sync, profile sync, and data transfer. | A cashier token no longer becomes owner authority merely because its JWT uses the parent business ID for normal data scope. |
| Local/cloud identity | A shared BizID is resolved to the owner record in the **current** database for generic sync, staff sync, profile sync, and data transfer. An unknown BizID returns 403; it never falls back to the numeric JWT ID. | Local and cloud can assign different integer IDs to the same business without misrouting data or control-plane writes. |
| Staff replication | Staff sync permits only `cashier` or `supply adder` roles. | Client sync payloads cannot provision owner-level staff. |
| Generic sync | Inbound B2B/cloud-authoritative rows are refused. Existing rows must belong to the requesting business; child rows prove ownership through their parent. Parent UID and raw-FK resolution is now tenant-scoped. | Known or guessed IDs/UIDs cannot update, delete, or attach to another business's records. |
| Data import | Owner-only access; mandatory ID remapping; unknown/global/shared-ledger tables rejected; owner identity resolved from the token, not payload usernames; client tenant fields are replaced with the destination owner. | Import files cannot use primary-key collisions or foreign business identifiers to overwrite another tenant. |
| Offline queue | Durable IndexedDB storage is physically partitioned by BizID and user ID. Queued operations carry the same immutable scope, cursors use scoped keys, and logout detaches the active scope. | Pending invoices from User A cannot be viewed or replayed under User B's login on the same browser/device. |
| Sales validation | HTTP schemas and billing commands reject zero/negative/non-finite quantities, negative/non-finite prices or money values, invalid tax/discount rates, and foreign product IDs; an excessive line discount is capped at the line gross amount. | A negative sale cannot create free inventory or corrupt invoice totals. |

## Important operational behaviour changes

- Existing browser entries in the legacy `bizassist_sync` IndexedDB database are deliberately **quarantined**, not automatically replayed under any new login. Reconcile them under the original account before retiring the old client version.
- Any older token lacking a `user_id` is refused for owner/control-plane actions. Re-authentication is required.
- Imports must use `remap_ids=true`; this is now the default and `remap_ids=false` is rejected.
- A local recovery flow is available only through loopback. A deliberately LAN-hosted backend cannot use that compatibility endpoint.
- `users.id` / `business_id` are database-local values. For any local-to-cloud or cloud-to-local operation, BizID is the identity contract and each side resolves its own numeric owner ID. A token carrying an unknown BizID is denied rather than matched by username or numeric ID.

## Mandatory verification gates

1. Restore the project Python 3.9 runtime or recreate the virtual environment, then run:

   ```powershell
   python -m pytest backend/tests/test_p0_isolation_hardening.py backend/tests/test_sync.py backend/tests/test_data_transfer.py backend/tests/test_sync_profile.py
   ```

2. Run the full backend suite against a disposable PostgreSQL database using the **same runtime database role** as cloud production.

3. Verify database migration head and RLS at runtime:

   - the application role cannot `BYPASSRLS`;
   - `FORCE ROW LEVEL SECURITY` is applied where expected;
   - tenant context is set for every request and job;
   - two tenants cannot read or mutate parent or child rows through direct API calls.

4. Perform browser end-to-end checks on a shared machine:

   - User A queues an invoice offline, logs out, and User B logs in;
   - User B sees no queue count, no User A cursor, and makes no User A request;
   - User A logs back in and can reconcile only User A's own queued work.

5. Run money/stock adversarial tests: negative/zero/NaN/infinite quantities and prices; retrying sale, payment, return, transfer, and import requests; two concurrent sales of the last unit; cross-tenant product/customer/godown IDs.

## Remaining hardening recommendations

### Financial and stock correctness

- Enforce cumulative return limits against original invoice/purchase lines, with return idempotency and original godown restoration.
- Replace floating-point money values with integer paise or `Decimal` at the command, persistence, and journal boundaries.
- Add locking or serializable retry around inventory availability so concurrent sales cannot oversell the same stock.
- Make every financial/stock mutation use an idempotency key, including returns, manual adjustments, purchases, and transfers.
- Route legacy uploads through canonical invoices, stock ledger movements, payment ledger entries, and journals; do not write reporting-cache tables as transactional truth.
- Make B2B completion transactional: seller sale/receivable, buyer purchase/payable, stock, and journals must either all commit or all remain pending for retry.

### Local + cloud ecosystem

- Replace LAN health-check discovery with explicit cryptographic device pairing. Never switch API targets or forward bearer credentials based only on a health response.
- Store cloud/device tokens in OS-backed secure storage, not browser local storage or plaintext files. Use short-lived, device-scoped tokens.
- Maintain a visible reconciliation console for quarantined queues, failed sync rows, financial conflicts, stock totals, and journal imbalances.
- Add a signed transactional outbox with exactly-once processing and a repair/reconciliation worker.

### Access and deployment controls

- Invalidate sessions immediately after staff password, role, or deletion changes; missing user/token-version records must fail closed.
- Rate-limit and reduce public identity/discovery/telemetry endpoints.
- Make staff permissions explicit per capability rather than treating every role other than cashier as owner-level.
- Require production secrets, CSP/XSS protections, dependency scanning, backup/restore drills, and monitored alerts before public launch.

## Verification performed in this workspace

- All modified backend Python files passed syntax compilation with the available bundled Python runtime.
- The changed offline-sync tests passed: **17/17**. Additional frontend suites covering hosting authentication, invoice math, POS helpers, hosting components, and billing profiles passed (**104 tests across the six completed suites**).
- `git diff --check` passed.
- Backend integration tests are currently blocked locally because the checked-in virtual environment points to a missing Python 3.9 installation. This is an environment issue, not a passing test result; it must be repaired before release.
- The complete frontend suite did not produce a clean completion in this sandbox: its worker remained active after the six passing suites above. Treat a clean full-suite run in CI/desktop runtime as a release gate; do not infer an all-suite pass from the partial run.

## Post-review regression fixes (backend rerun required)

A supplied backend run reported four failures after the initial P0 patch. All
four were investigated and addressed:

- Excessive absolute discounts are again capped at the line gross amount (free
  line), never allowed to produce a negative taxable value.
- The sync deferral call retains its deliberate source-level regression marker;
  the deferral/ack behaviour itself was not changed.
- A source UID that already exists under another tenant no longer causes the
  parent import to be skipped. The destination derives a deterministic scoped
  UID, so repeat imports remain idempotent.
- A colliding invoice public-share token (`uid_token`) is similarly regenerated
  deterministically for the destination; public links are never shared across
  tenants merely to make an import succeed.
- Child UID matching is now scoped through the destination parent business;
  foreign child rows cannot be mistaken for an existing import target.

The sandbox cannot rerun pytest because its checked-in Python 3.9 virtual
environment points to a deleted interpreter. Run the four formerly failing
tests and the P0 suite again in the working test environment before release.

## Final recommendation

Treat this as a **hardening milestone, not a production approval**. The P0 code paths are now fail-closed in source, but release approval requires the mandatory staging and packaged-runtime checks above. No financial system is “100% certain” based on source inspection alone; certainty comes from enforced invariants, adversarial tests, production-role database verification, monitoring, and recovery drills.
