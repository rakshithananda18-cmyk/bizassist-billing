# Database authority and protocol deployment contract

This is a deployment contract, not evidence that production is configured.
The synthetic PostgreSQL tests establish the code path and denied operations.
An authorized database operator must verify that the hosting provider permits
the required roles/function ownership and apply the real grants. Never substitute
a superuser connection for the normal HTTP runtime to make a failing test pass.

| Identity | Required authority | Credential location |
| --- | --- | --- |
| Schema/operator | Owns schema/tables and runs Alembic; superuser or PostgreSQL 16 NOSUPERUSER BYPASSRLS CREATEROLE with role-administration permission for the bootstrap role | Migration process only |
| HTTP runtime | LOGIN, NOSUPERUSER, NOBYPASSRLS; tenant data grants and fixed bootstrap EXECUTE grants | `DATABASE_URL` on the API server |
| Bootstrap | NOLOGIN, BYPASSRLS; required User/invoice/settings reads and fixed actor-lock privilege; only fixed security-definer functions expose results | No login credential |
| Internal trade | LOGIN, NOSUPERUSER, BYPASSRLS; exact trade table grants and only public User columns; no credential/settings SELECT | `DATABASE_TRADE_SERVICE_URL`, server secret |
| Platform admin | LOGIN, NOSUPERUSER, BYPASSRLS; known Billing operational DML, feed inspection only, and SELECT/DELETE on supported Field cleanup tables | `ADMIN_SERVICE_URL`, separate server secret |

The runtime, trade and admin roles must be distinct. They must not inherit or
have membership/SET ROLE access to one another or to privileged schema/operator
roles. Do not grant CREATE on the public schema, role administration, grant
option or general SQL endpoints to the HTTP role. Verify existing grants and
memberships as well as the new grants; an additive migration is not proof that
old excessive grants were revoked.

A non-superuser schema operator needs both SET membership and inherited
ownership privileges in `bizassist_bootstrap`. The installer gives these to
the already privileged **migration operator only**, before creating/replacing
functions. PostgreSQL 16's automatic ADMIN membership for a newly created role
does not itself provide these rights. If the bootstrap already exists and
another principal created it, an authorized role administrator must first give
the intended schema operator ADMIN option on that role. The installer must not
give any such membership to the constrained HTTP runtime.

During ownership transfer, PostgreSQL also requires the new function owner to
have CREATE on `public`. The installer grants this to the NOLOGIN bootstrap
temporarily and revokes it after all fixed functions change owner, inside the
same migration transaction. Bootstrap keeps schema USAGE and its narrow table
rights. Operator SET/inherited ownership rights remain for repeated
`CREATE OR REPLACE`; the fixed functions explicitly grant operator EXECUTE so a
legacy deployment still using that privileged operator can authenticate after
PUBLIC EXECUTE has been revoked. This compatibility does not grant those
operator privileges to the normal constrained HTTP role.

Provision the roles with separately generated credentials using the provider's
authorized secret-management path. Set `BIZASSIST_RUNTIME_DB_ROLE`,
`BIZASSIST_TRADE_DB_ROLE` and `BIZASSIST_ADMIN_DB_ROLE` in the migration process,
and execute `alembic upgrade head` from `backend/` under schema/operator
credentials. Head is `e70b5d2a4c06`; it follows `d60a4c1f3b05` and installs the
configured admin grants. Reapply the installers under schema authority when a
later Field migration creates a supported cleanup table. Unknown Field tables
or reference layouts deliberately stop deletion pending an explicit cleanup
update. The admin role has no general Field INSERT/UPDATE grant.

Run the HTTP server with its constrained `DATABASE_URL`, and supply the two
separate service URLs only to the server. The admin URL must address the same
database as the API. Admin endpoints also require `ADMIN_API_ENABLED=1`, an
already authenticated live admin owner, and a matching live token version.
Role/version checks repeat under a row-share lock at every service transaction,
including after a helper commits an audit entry. No route hands this session to
a merchant. Ordinary B2B service entry revalidates the authenticated party,
accepted connection, order ownership and locked live business identities. Missing
service configuration returns 503 instead of an RLS-filtered empty result or a
fallback to a more privileged general connection.

Upgrade server and device builds for sync protocol 2 before resuming incremental
replication. Legacy incremental peers receive 426 and preserve their queue/cursor;
operators must upgrade them. Database triggers capture changes and publish
per-business revisions in commit order. Old control events without provable
original identity are cancelled, never replayed using a new business token.

The required release checks are the complete historical migration chain on
fresh SQLite/PostgreSQL, retry/idempotence and current-schema parity, plus
`python backend/tests/run_sync_role_smoke.py` against an explicitly disposable
loopback test database. The latter provisions synthetic runtime, trade and
admin roles; it never reads a developer `.env` and never prints passwords. Also
run `python backend/tests/run_nonsuperuser_security_smoke.py` with
`TS_SCHEMA_ADMIN_DATABASE_URL` pointing only to the disposable loopback control
database. It creates fresh synthetic operator/runtime credentials and a fresh
test database, runs the entire historical chain and retry as a non-superuser,
repeats ownership-transfer installation, and checks owner/staff/public-token
authentication plus denied runtime memberships/CREATE. The full-schema-chain CI
job runs this proof using its PostgreSQL 16 service. Optional
`TS_SECURITY_PROOF_OUTPUT` selects a JSON result path; credentials never enter
that report. The recorded local run passed nine checks in 14.88 seconds. Also
complete real staging/device restart/reconnect, multi-process revocation and
backup/restore checks before claiming operational deployment readiness.

Rotate the confirmed exposed Supabase database password through the provider,
update dependent server secrets, and record revocation verification separately.
Current source cleanup and these local synthetic role tests do not perform or
verify that external action.
