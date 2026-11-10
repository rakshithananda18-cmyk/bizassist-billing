# Trust, sync and database authority implementation — 31 October 2026

All nine original trust/sync issues are fixed in the current working tree. Real
constrained-role customer, B2B and platform-admin flows pass. Production
role/credential provisioning remains an explicit deployment gate. The
[per-issue ledger](trust-sync-status.json) records the exact distinction; the
[verification record](trust-sync-results.json) separates current results from
preserved historical diagnostics.

The timestamp cursor has been replaced by a transaction-bound database change
feed. Per-business revision locks serialize PostgreSQL publication through
commit; SQLite serializes writers. Source triggers also capture raw SQL. The
worker uses protocol 2 and retains its cursor/queue when either peer needs an
upgrade. The control outbox shares the caller's transaction, leases delivery,
holds successors behind failed predecessors, and binds events to the original
BizID plus contiguous device revision. Receiver receipts make response-loss
retries idempotent. Purge/reclaim removes old control state before a new
identity can use it.

Narrow security-definer bootstrap functions enable login, signup, public invoice
tokens and live subject checks without giving the HTTP role general cross-tenant
access. Bilateral B2B posting uses a separately configured internal trade
credential, explicit actor/connection/order checks and restricted table/column
grants. The service cannot select User password/settings columns. Audit
ownership follows the mutated row rather than assigning buyer-private stock and
purchase details to the seller who completed the shared order.

Root independently verified **11 tests passing in 8.90s** on a disposable local
PostgreSQL database, using a real NOSUPERUSER NOBYPASSRLS HTTP role and separate
trade role. This includes concurrent commit visibility, full signup/login/staff/
paid/public paths and B2B request/approval/catalog/order/fulfilment/posting with
private-ledger and audit isolation. Root also verified the complete historical
Alembic chain and repeated upgrade on fresh SQLite and PostgreSQL through
`d60a4c1f3b05`, with parity checks for all 66 model tables. The role smoke itself
starts with current metadata; it is not the historical-chain proof.

The subsequent direct trust-agent run passed **12 tests in 13.60s**, including
the new separate platform-admin service. Actual fleet/campaign-preview HTTP
calls succeed for a live admin, normal owners and false admin role claims are
denied, missing configuration returns 503, and a token-version change is checked
again after a service commit. A minimal synthetic FORCE-RLS Field table verifies
maintenance cleanup using only its SELECT/DELETE grants. No messages are sent.
Admin sessions recheck the subject's role/version under a row-share lock on
every transaction. Merchant announcements continue to evaluate their own bound
tenant lazily; there is no global campaign sending scheduler. Desktop log
upload now exits on PostgreSQL. The separate SQLite admin/campaign run had no
behavior failures; its one obsolete tenant-audit allowance was removed and the
final tenant gate passed 14 tests. Initial and final logs are preserved.

Control compatibility checks also passed all staff/profile/WP2/WP3/P0 cases.
Valid fixtures now send explicit identity/revision envelopes; legacy owner
profile and staff messages still require an upgrade with 426. The initial
37-pass run had one snapshot-count assumption in the sync lifecycle test;
the fixture now checks the unique customer UID and every delivered value in
the revision feed, and its final two-test rerun passed. No receiver security
behavior was relaxed to satisfy old fixtures.

The final broad-suite follow-up also verified worker chunk success and partial
failure using the required cloud token. Failed-login logging again names a
known account using only the narrow existence helper and hides unknown typed
input. The audit regression now exercises real inserted/updated/deleted audit
rows and confirms the owning BizID even with a different request actor. The
three-file run passed 47 cases; its single new fixture omission was corrected,
and the native audit case then passed separately. Exact logs/counts are in the
verification record; overlapping reruns are not summed as unique tests.

Production provisioning remains separate: apply migrations with schema-owner
credentials through head `e70b5d2a4c06`, configure runtime/trade/admin roles and
their separate server-only service DSNs, and roll out compatible protocol-2
peers. Missing trade/admin credentials deliberately fail closed. Follow the
[role deployment contract](trust-role-deployment.md); hosted-provider permissions
and actual live grants still require verification. No production configuration,
deployment or external password rotation was performed. The owner's confirmed
unrotated/uncertain Supabase
password exposure remains an immediate external action in the
[security response](../SECURITY-RESPONSE.md).

A subsequent provider preflight exposed a missing privilege in the installer:
a non-superuser schema operator needs SET/inherited ownership rights in the
bootstrap role, and the new function owner needs temporary schema CREATE during
ownership transfer. The installer now grants these only to the privileged
operator/bootstrap as appropriate, revokes bootstrap CREATE in the same
transaction, and explicitly preserves operator EXECUTE on the fixed functions.
The constrained HTTP role receives no privileged membership. A dedicated local
PostgreSQL 16 proof ran the complete historical chain, retry, repeated function
replacement and owner/staff/public-token authentication under a real
NOSUPERUSER BYPASSRLS CREATEROLE operator: **9 checks passed in 14.88s**. It also
verified revoked bootstrap CREATE/PUBLIC EXECUTE and absent runtime memberships.
The existing cluster-global bootstrap was preserved; a separate generated role
verified non-superuser creation of NOLOGIN BYPASSRLS roles. This proof is now
part of the full-schema-chain CI job. No production connection was used for
this fix or proof.
