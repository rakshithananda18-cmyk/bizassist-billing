# Cloud readiness continuation — 2026-10-29

This continues [the Billing/Field/POS review](2026-10-29-field-and-pos-review.md).
These checks were completed before publication. No production deployment,
migration, business record, subscription or secret was changed during the checks.
The user subsequently authorized publishing the complete reviewed source batch
to GitHub and the Hugging Face Billing Space.

## Deployed public checks

The read-only `dev/check_cloud_release.py` run passed all six checks:

| Check | Result |
| --- | --- |
| Billing cloud `/health` | HTTP 200, connected PostgreSQL, cloud mode |
| Field Team `/api/health` | HTTP 200, reports PostgreSQL; the currently deployed endpoint does not perform the new round-trip check |
| Billing and Field Team Vercel frontends | Both HTTP 200 HTML |
| Billing handoff CORS from Billing frontend | Allowed; explicit frontend origin |
| Field exchange CORS from Field frontend | Allowed; explicit frontend origin |

Read-only Cloud Run metadata showed service `bizassist-task`, revision
`bizassist-task-00008-btw`, Pro flag `1`, the Field Vercel origin allowed,
purge loop `0`, and database/signing-key values supplied by Secret Manager.
Secret values were not printed or compared. This does not prove that Billing
and Field use identical database or signing-key values.

## Additional issues fixed

- Field Team previously set tenant scope once per request using a connection-wide setting. A commit can release that connection before later ORM serialization, allowing the next transaction to run without the intended scope. It now stores the authenticated business on the Session, reapplies transaction-local scope after every transaction begins, and resets legacy pool state on checkout. PostgreSQL connection establishment is bounded to five seconds.
- The Field image CI smoke run used an implicit SQLite fallback that the new production guard correctly refuses. It now uses an explicitly isolated fixture. PostgreSQL test jobs opt out of Pro only for disposable free fixture owners, while deployed Pro enforcement remains mandatory.
- A deployed mirror flag could otherwise ask Field Team to create/alter Billing-owned tables. Deployment now refuses that flag on PostgreSQL as well as SQLite.
- Field health previously returned `ok: true` using only the dialect name. The new endpoint executes `SELECT 1`, returns 503 on database failure without driver details, and reports safe Pro/mirror/cloud-only flags. The deploy script checks the stronger contract.
- Added a repeatable public preflight with bounded requests and sanitized reports. It performs only GET and OPTIONS requests, never signs in or books financial records.

## Billing caching

React/router is now a separate stable framework chunk. Sales and checkout stay
eagerly loaded to preserve existing offline behavior. Production build and
browser login/register navigation passed without runtime errors; the static
chunk graph has no cycles and all 14 lazy routes remain.

The app chunk is 503.14 kB / 135.27 kB gzip, plus framework 165.45 kB /
53.91 kB gzip. Total initial gzip changed from 188,628 to 189,176 bytes
(+548 bytes). This improves repeat-visit caching between app releases, not
first-load size. The 500 kB app-chunk warning remains.

## Verification

- Public preflight: six checks passed; eight mocked CLI regressions passed.
- Restricted-role PostgreSQL isolation: all five transaction/pool tests passed, including actual `NOBYPASSRLS` policy checks.
- Full Field backend suite on disposable PostgreSQL: 132 passed, four external Billing contract tests skipped for their separate full-schema run.
- Full Field backend suite on disposable SQLite: 130 passed, six skipped (the four external Billing cases and two PostgreSQL-only cases).
- Full Field backend suite against Billing's complete schema on a second disposable PostgreSQL database: **136 passed, zero skipped**. This includes Billing-minted handoff tickets, shared model/plan/payment-key contracts, migrations, live-balance workflows and restricted-role tenant checks.
- PowerShell deployment-script parsing and repository whitespace checks passed.

The loopback PostgreSQL cluster and production preview server were stopped
after verification; existing application/database services were left running.

## Final UI and publication preparation

At the user's request, the duplicate Billing/Field Team switcher was removed
from the sidebar brand header. Both desktop and mobile profile-menu switchers
remain, with the existing role, Pro and cloud-source checks. Browser verification
confirmed the clear header and working profile-menu placement. The final focused
sidebar/handoff/collection/workspace-guard run passed 24 tests, and the Billing
production build passed (app 502.99 kB / 135.27 kB gzip).

Publishing the source to GitHub and Hugging Face is separate from deploying the
Field Team API to Cloud Run. The public checks above describe revision
`bizassist-task-00008-btw`; they do not establish that the new Field API code is
already running there.

## Remaining release checks

After publishing the reviewed changes, run:

```powershell
python dev/check_cloud_release.py --require-field-flags --report scratch/cloud-release-after-deploy.json
```

Then validate a dedicated cloud QA business through owner handoff, matching
BizID and Pro entitlement, linked customer/invoice reads, updated balances and
the collect/confirm cycle. Public availability does not establish those results.
Neither real local database should be repointed or merged.

This PC has only virtual/document printer drivers (PDF/XPS/OneNote/Fax).
Physical receipt width, cutting and printer-driver output remain unverified.
