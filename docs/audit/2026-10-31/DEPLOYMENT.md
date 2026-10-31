# Deployment preflight and applied schema — 31 October 2026

The owner requested GitHub and Hugging Face publication, then explicitly approved
moving the existing database URL into a Space secret, encrypted local recovery
copies and the five pending Alembic upgrades. This record covers the completed
pre-push operations. Remote commit and runtime confirmation follow publication.

## Applied and verified

- Target Space: `rakshit-dev/BizAssist`. Its `DATABASE_URL` was a public variable;
  it is now a secret with the identical value, and the public variable is absent.
  The database password was not changed or rotated.
- A PostgreSQL 17.6 custom-format backup of the application's complete `public`
  schema was encrypted with AES-GCM and a Windows DPAPI-protected key. Decryption,
  hash comparison, archive directory parsing and complete archive read/decompression
  passed. No plaintext backup file was written. This is an application-schema
  backup, not a backup of Supabase-managed schemas or a completed full restore drill.
- The live revision advanced from `f7b8c9d0e1f2` through `a30f1d7b9c02`,
  `b40e2c8d1f03`, `c50f3b9e2a04`, `d60a4c1f3b05` to **`e70b5d2a4c06`**.
  A second `alembic upgrade head` completed successfully.
- Fingerprints of the pre-existing columns in 16 identity, catalogue and
  financial tables matched before and after. No receipt, invoice line, stock
  movement, journal or business identity was repaired or reassigned.
- The installed bootstrap helper executed successfully and its temporary schema
  CREATE privilege was confirmed revoked.

Recovery artifacts are under ignored `.private/deployment/`. They are protected
for the current Windows user and must not be committed, uploaded into the Space
build, or treated as an independent off-machine disaster-recovery system.

## Permission fix discovered during preflight

Supabase's current schema operator has BYPASSRLS and CREATEROLE without being a
superuser. The original installer tests used a superuser and missed the
ownership-transfer requirements. The installer now gives the schema operator
the ownership membership required for repeated function replacement, grants
bootstrap schema CREATE only during ownership transfer, then revokes CREATE
before the transaction completes. The constrained HTTP role receives no
privileged membership. Operator EXECUTE on the fixed helpers is explicit.

The [native non-superuser proof](implementation/trust-nonsuperuser-security.json)
passed nine checks: complete fresh migration, upgrade retry, repeated installers,
privilege catalog assertions and constrained owner/staff/public-token access.
`backend/tests/run_nonsuperuser_security_smoke.py` is now a CI gate. The ownership
requirements are documented by [PostgreSQL](https://www.postgresql.org/docs/16/sql-alterfunction.html).

The current Space still uses its existing privileged operator connection.
Dedicated constrained HTTP, trade and admin credentials remain a separate
deployment change; this publication does not claim that transition is complete.

## Source publication checks

Intended refs are GitHub `main` and `codex/audit-2026-10-30`, and Hugging Face
`main`. Both remote main branches were ancestors of the reviewed source; no
force push or history rewrite is intended.

The staged source-hygiene gate passed. Gitleaks reported 49 file-digest false
positives initially; source manifests now separate paths from SHA256 fields,
preserving their values. The staged scan then passed without adding scanner
exclusions or weakening rules. Private credentials, the backup, local databases
and operational exports remain outside Git and Docker build contexts.

The preceding acceptance includes 2,526 backend tests, 883 Billing frontend
tests, 165 Field tests on the real migrated PostgreSQL schema, and 89 Field
frontend tests. Exact scopes and skips remain in the [acceptance record](implementation/root-results.json).

## Remaining work

Rotate the previously exposed password and update all dependent deployments;
moving one configuration value into a secret does not revoke historical copies.
Reconcile the historical receipt/shift/overfill discrepancies from original
evidence. Complete independent recovery, real devices/printers, protocol-2 client
rollout and the paid merchant pilot. Field's separate hosting service, desktop
releases and external frontend deployment hooks are not proved deployed merely
by pushing the Billing Space.
