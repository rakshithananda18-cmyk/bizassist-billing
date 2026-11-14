# Backend security review — 2026-11-13

The SonarCloud baseline is the previous version from 2026-07-01. This change
addresses backend findings without lowering quality conditions or excluding
application code from analysis.

- Repair tools restrict filesystem reads and evidence writes to
  `BIZASSIST_OPERATIONS_ROOT` (repository root when unset). Set it explicitly
  to an approved directory when working on an external database copy. Paths
  containing parent traversal or escaping through a symlink are rejected.
  Evidence files are private and created exclusively: an earlier backup is
  never overwritten.
- SQLite inspection percent-encodes filename delimiters before adding the fixed
  read-only option. PostgreSQL credentials and options become explicit driver
  keyword values; query parameters cannot override the server, database or
  credentials. Remote PostgreSQL connections require TLS.
- Migration endpoints must be loopback or HTTPS origins explicitly named in
  `BIZASSIST_MIGRATION_ORIGINS`; the established billing cloud origin is allowed
  by default. Redirects are disabled so a credential cannot be forwarded to an
  unapproved target. Backfill receives a validated single `--db=...` argument.
- Local secret files use fixed filenames under the selected data directory,
  private temporary files, atomic replacement, and symlink refusal. Secret file
  contents are data, never a destination path. The previous S2083 trace followed
  secret *contents* into `Path.write_text(data)`; it did not show attacker control
  of the filename. The new writes also provide real durability/permission gains.
- API diagnostic values escape record and terminal separators before logging.
  Customer names are omitted from the invalid-customer-link diagnostic.
- Local `serve.py` binds loopback by default. Both container images explicitly
  configure `BIND_HOST=0.0.0.0` because Cloud Run/HF require a container listener.
- Optional object-storage telemetry archival requires
  `TELEMETRY_ARCHIVE_S3_EXPECTED_OWNER`, supplied to `ExpectedBucketOwner`.
  Configure the actual account identifier supported by the chosen provider;
  unsupported ownership verification must not be represented as a successful
  archive. Failed uploads retain the existing maintenance fallback behavior.

## Protocol-specific review

**TOTP (python:S4790):** existing enrollments specify `algorithm=SHA1`. RFC4226
and RFC6238 use HMAC-SHA1, a keyed MAC, rather than a collision-sensitive bare
SHA1 password hash/signature. Changing this algorithm would invalidate existing
authenticators. The implementation now explicitly uses `hmac.digest`, and
`test_operational_security.py` checks the six published RFC6238 Appendix B SHA1
vectors. A finding on this exact protocol construction requires contextual
review, not a silent algorithm change. See https://www.rfc-editor.org/rfc/rfc6238.

**LAN discovery (python:S5332):** the registry describes an existing service;
it does not make an HTTP request or transmit credentials. Legacy local servers
currently speak HTTP. Advertising HTTPS does not create TLS and would break
discovery. Registration now explicitly carries its actual `http`/`https` scheme,
only validated non-public LAN addresses can be described, and persisted public
or non-HTTP entries are not advertised. HTTPS is preserved for servers already
configured with TLS. Plaintext LAN HTTP remains plaintext; a full TLS rollout
requires certificate/trust provisioning and client changes. Any remaining
descriptor-only finding needs this context, rather than changing a label to
claim encryption that is absent.
