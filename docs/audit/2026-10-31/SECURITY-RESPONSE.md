# Database credential exposure response — 31 October 2026

## Evidence and completed source containment

A redacted Gitleaks 8.18.4 history scan reported 117 candidates. Four occurrences
in four diagnostic scripts contain the same non-placeholder cloud database
credential. Other candidates include example connection strings, a public Sonar
project identifier and old idempotency log keys; the 117 candidates are not 117
confirmed secrets. No secret values are reproduced here.

Affected current paths: `backend/check_cloud_db.py`, `backend/cloud_db_check.py`,
`backend/compare_schema.py`, and `backend/dump_schema.py`. The scripts now require
an explicit `BIZASSIST_AUDIT_DATABASE_URL`, contain no built-in database URL and
perform no connection on import. Regression checks exercise safe imports.

A final in-memory check compared the confirmed historical password against all
current Git-eligible files and found zero matches. The value was not printed or
written to a report. This verifies current source containment, not revocation
or removal from historical commits.

During the subsequently approved deployment preflight, the same Space database
connection was moved from a public variable into a secret, with an encrypted
private recovery copy. The public variable is absent. This containment did not
rotate the database password; the remaining provider-side work below is still
required. See [the deployment record](DEPLOYMENT.md).

The deployment metadata checks reported both the configured GitHub repository
and Hugging Face Space as public. Their historical commits remain reachable;
source cleanup and hiding the current variable do not revoke the exposed
credential. Provider rotation is still urgent.

The three operational repair JSON exports have been removed from the Git index,
retained locally under ignore coverage, encrypted with AES-GCM and a Windows
DPAPI-wrapped key, and recovered byte for byte in a local verification. Their
historical URL scan findings use redacted placeholders, distinct from the four
confirmed credential occurrences. Keep the Windows profile recovery key safe;
the local vault is not an independent off-machine disaster-recovery backup.

## Required external work

1. Rotate the exposed project database password in Supabase. Do not reuse it or
   paste either password into chat, source, a command transcript or an issue.
2. Update the configured database connection secrets for Billing, Field Team,
   backup jobs and any local operational configuration. Use their existing
   secret stores. Include schema-admin/runtime/trade-service credentials where
   those roles have been provisioned; prefer separate least-privilege roles.
3. Restart connection pools using the new configuration. Verify authenticated
   health and a controlled synthetic transaction in staging before promotion.
4. Verify the old credential is no longer accepted through the provider's
   administrative controls. Review database and deployment access logs for the
   exposure window. No conclusion about unauthorized access has been made.
5. Assess published GitHub/Hugging Face history, release bundles, forks and
   clones. If history cleanup is chosen, first preserve a private encrypted
   repository backup, prepare the exact affected refs in an isolated mirror,
   review the rewrite, then coordinate its push and fresh clones. History
   cleanup does not replace password rotation. No rewrite or force push was
   performed during this task.

The code changes cannot prove or perform these account-side steps without the
appropriate connected account access and deployment coordination. Rotation
remains open following the owner's “Not yet / unsure” response.
