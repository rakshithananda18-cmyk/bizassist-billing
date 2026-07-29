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
| B2B completion (2026-07-29) | Completing an order now creates the seller sale/receivable, buyer stock receipt, buyer Purchase Bill/payable, and both journals inside one transaction. The buyer bill uses a deterministic UID based on the shared order UID. Raw buyer/seller document IDs remain inside their owning tenant; the counterparty receives only posted-state confirmation. A successful local-to-cloud B2B write schedules an immediate cloud-to-local pull. | A completion retry cannot double stock or double-post money, an interrupted completion rolls back rather than leaving one business's books ahead of the other, cross-tenant integer IDs cannot be reused by the UI, and the local Purchase Bills screen does not have to wait for the regular pull cadence. |
| Legacy B2B receipts (2026-07-29) | A buyer-owner-only reconciliation action creates a missing Purchase Bill from a completed supplier invoice without making any stock movement. The response separately reports whether a linked buyer stock receipt actually exists. | Historical books can be repaired even when older orders predate the receipt link; the operation cannot receive goods twice, and the UI no longer claims “Stock received” without ledger proof. |
| Manual stock adjustments (2026-07-29) | The append-only ledger is now the sole quantity writer. Batch and expiry metadata travel with the movement; the inventory projection is updated only as a cache and never receives the delta twice. The UI treats any non-2xx response as unsaved. | A batch adjustment is reconstructable from the ledger, cannot double its quantity in the cache, and a generic 409 cannot make staff believe stock was saved when it was not. |
| Fractional inventory (2026-07-29) | `inventory.stock` now uses fractional precision and the cloud startup/Alembic migration upgrades PostgreSQL from INTEGER to DOUBLE PRECISION. Ledger cache refresh and rebuild retain the exact quantity. | Weight, length, and volume items no longer have their cached stock (and therefore valuation) rounded to whole units. |
| Purchase Bill confirmation (2026-07-29) | The normal supplier-bill command now validates every item before any database write: non-empty bill, positive finite quantity/conversion factor, finite non-negative price, valid GST rates, and a positive reconciled total. It derives persisted line/header totals from the reviewed quantity/rate and rejects a non-zero claimed header total that conflicts with those lines. Removing an OCR row recalculates the browser draft; server validation errors are shown to the owner. | The stock receipt, Purchase Bill, payable, and journal cannot be posted with an empty/zero/NaN line or a stale total from a deleted OCR item. |

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

6. Run the normal Purchase Bill flow against a disposable database: create a bill, edit its quantity/rate, remove a line, retry the request, and verify exactly one purchase invoice, matching line totals, one stock-ledger receipt per line, and one balanced journal entry. Also verify that an empty bill, zero quantity, and conflicting header total return 422 and commit nothing.

## Remaining hardening recommendations

### Financial and stock correctness

- Before rebuilding historical inventory caches, audit legacy batch rows. Older builds could hold batch labels only in the cache while their ledger movements were unbatched; a blind global rebuild cannot infer that missing historical batch attribution. The ledger total remains authoritative, but affected batches need an owner-reviewed reconciliation rather than an automatic rewrite.
- Enforce cumulative return limits against original invoice/purchase lines, with return idempotency and original godown restoration.
- Replace floating-point money values with integer paise or `Decimal` at the command, persistence, and journal boundaries.
- Add locking or serializable retry around inventory availability so concurrent sales cannot oversell the same stock.
- Make every financial/stock mutation use an idempotency key, including returns, manual adjustments, purchases, and transfers.
- Route legacy uploads through canonical invoices, stock ledger movements, payment ledger entries, and journals; do not write reporting-cache tables as transactional truth.

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

- All modified backend Python files, including the B2B completion/reconciliation, stock-adjustment, and fractional-quantity paths, passed syntax compilation with the bundled Python runtime.
- The targeted B2B frontend test suite passed (**13/13**). After the latest Purchase Bill changes, the complete billing frontend suite passed (**50 files, 349 tests**) and the production frontend build passed.
- The backend regression tests now cover: generated buyer Purchase Bill, balanced buyer purchase journal, exactly-once retry, legacy-bill reconciliation with and without a linked stock receipt (never duplicate stock), immediate local projection after a successful cloud B2B write, one-time batch adjustments, fractional inventory cache rebuilds, and rejected empty/zero/mismatched Purchase Bill drafts.
- Backend integration tests cannot be rerun in this Codex environment because the checked-in virtual environment points to a deleted Python 3.9 interpreter. A Python 3.12 fallback cannot load its Python 3.9 compiled dependencies. This is an environment limitation, not a passing backend result; run `run_tests.bat fast` from the repaired working runtime before release.
- The user previously supplied a clean `run_tests.bat fast` result for the earlier P0 work (`backend: PASS`, `frontend: PASS`). The new B2B backend test changes post-date that result and still require the explicit backend rerun above.

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
