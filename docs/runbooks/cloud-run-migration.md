# Cloud Run migration release runbook

Back up PostgreSQL before applying migrations. Apply Billing Alembic head
`h4_auth_admin_runtime_state` with the schema operator, and the Field Team head,
before a constrained runtime starts. Never paste credentials into reports or
commit .env files. Test the tagged revision before moving production traffic.
The Vercel console changes below were reported completed by the owner; verify
the deployed builds and certificate after deploying the source changes.

The tagged rollout follows [Cloud Run traffic migration](https://docs.cloud.google.com/run/docs/rollouts-rollbacks-traffic-migration).
External jobs use [Cloud Scheduler HTTP targets](https://docs.cloud.google.com/sdk/gcloud/reference/scheduler/jobs/create/http).



The user runs these steps after the code tasks are merged, in deploy order, from the repository root in Windows PowerShell; `docs/runbooks/cloud-run-migration.md` (leaf 18.10) mirrors them.

1. Field Team API redeploy and its readiness gate (2.9)
   - Command: `.\backend-task\deploy_cloudrun.ps1 -Project <field-team-project-id> -AllowedOrigins "https://bizassist-task.vercel.app"`
   - Verify: `curl.exe -s https://bizassist-task-qyfsbxu27a-el.a.run.app/api/health` shows `pro_required: true`, `billing_mirror: false` and `cloud_only: true`.
   - Verify: `curl.exe -si -X OPTIONS https://bizassist-task-qyfsbxu27a-el.a.run.app/api/auth/exchange -H "Origin: https://bizassist-task.vercel.app" -H "Access-Control-Request-Method: POST"` returns status 200 with the header `access-control-allow-origin: https://bizassist-task.vercel.app`.
   - Rollback: if this API is rolled back after step 3, it refuses the 90 s tickets that the billing API mints. Run `gcloud run services update staterbill-api --project staterbill --region asia-south1 --update-env-vars HANDOFF_TTL_FIELD_TEAM=55`.

2. Shared `JWT_SECRET` and `DATABASE_URL`
   - Command: compute the SHA-256 digest of both secrets in each project. Run the snippet once as written and once with `$project = '<field-team-project-id>'`. It prints only the digests and clears each value after hashing it.

     ```powershell
     $project = 'staterbill'
     foreach ($name in 'JWT_SECRET', 'DATABASE_URL') {
         $secret = gcloud secrets versions access latest --secret $name --project $project
         $digest = [Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($secret))
         Remove-Variable secret
         $hex = ([BitConverter]::ToString($digest) -replace '-', '').ToLower()
         "$project $name $hex"
     }
     ```

   - Verify: `python dev/check_cloud_release.py --jwt-sha256-billing <staterbill JWT_SECRET digest> --jwt-sha256-field <field-team JWT_SECRET digest> --db-sha256-billing <staterbill DATABASE_URL digest> --db-sha256-field <field-team DATABASE_URL digest>` reports `match` for both pairs.

3. Billing API deploy, `BILLING_CRON_SECRET` and the Scheduler jobs (18.3)
   - Command: `.\backend\deploy_cloudrun.ps1 -Project staterbill -Setup`. The first run creates `BILLING_CRON_SECRET` and the Cloud Scheduler jobs; later deploys run the same command without `-Setup`.
   - Optional, only if the runtime database role is moved to a constrained role: before the deploy, create the `ADMIN_SERVICE_URL` secret in the Google Cloud console (project `staterbill` → Security → Secret Manager → Create secret). Verify: `gcloud secrets describe ADMIN_SERVICE_URL --project staterbill` shows the secret's metadata, not its value.
   - Verify: `curl.exe -s https://staterbill-api-1076771386585.asia-south1.run.app/health` returns ok.
   - Verify: `gcloud scheduler jobs list --project staterbill --location asia-south1` lists the jobs that `-Setup` created, each `ENABLED`.
   - Verify: `gcloud run services describe staterbill-api --project staterbill --region asia-south1` shows max instances 1 and `SUBSCRIPTION_ENFORCED=0`.
   - Rollback: move traffic back with `gcloud run services update-traffic staterbill-api --to-revisions <rev>=100 --project staterbill --region asia-south1`. If `<rev>` is from before task 16.4, first pause each Scheduler job with `gcloud scheduler jobs pause <job> --project staterbill --location asia-south1`, and resume it with `gcloud scheduler jobs resume <job> --project staterbill --location asia-south1` once traffic is on a revision with 16.4 again.

4. Hugging Face forwarder (2.33)
   - Command: replace the Space's contents with `ops/hf-forwarder/`. When Git asks for a password, give a Hugging Face access token with write access.

     ```powershell
     $space = "$env:TEMP\hf-bizassist"
     git clone https://huggingface.co/spaces/rakshit-dev/bizassist $space
     git -C $space rm -r -q .
     Copy-Item -Recurse -Force .\ops\hf-forwarder\* $space
     git -C $space add -A
     git -C $space commit -m "Replace the Space with the Cloud Run forwarder"
     git -C $space push
     ```

   - Verify, once the Space shows Running: `curl.exe -s https://rakshit-dev-bizassist.hf.space/__forwarder` answers, and `curl.exe -s https://rakshit-dev-bizassist.hf.space/health` returns the Cloud Run health JSON (`"db_type":"postgresql"`).
   - Rollback: `git -C $space revert --no-edit HEAD`, then `git -C $space push`.

5. Vercel frontends
   - (a) www domain and certificate (2.52): Vercel dashboard → billing project → Settings → Domains → add `www.staterbill.com`, redirecting to `staterbill.com`, then add the DNS record that Vercel shows at the DNS provider. Verify: `curl.exe -sI https://www.staterbill.com` shows a 308 to `https://staterbill.com` with no certificate error.
   - (b) Deployment Protection (2.11): Vercel dashboard → AI dashboard project → Settings → Deployment Protection → turn off Vercel Authentication for Production. Verify: `curl.exe -sI https://bizassist-dev-workspace-ai.vercel.app/` returns 200, not a 302 to `vercel.com/sso-api`.
   - (c) Production environment variables (2.54): in each project, Settings → Environment Variables, scoped to Production. A comma-separated `VITE_BILLING_URL` works only after tasks 9 and 10 are deployed.

     | Project | Variable | Value |
     |---|---|---|
     | frontend-billing | `VITE_API_URL` | `https://staterbill-api-1076771386585.asia-south1.run.app` |
     | frontend-billing | `VITE_FIELD_TEAM_URL` | `https://bizassist-task.vercel.app` |
     | frontend-billing | `VITE_AI_DASHBOARD_URL` | `https://bizassist-dev-workspace-ai.vercel.app` |
     | frontend-billing | `VITE_PUBLIC_WEB_URL` | `https://staterbill.com` |
     | frontend-task | `VITE_API_URL` | `https://bizassist-task-qyfsbxu27a-el.a.run.app` |
     | frontend-task | `VITE_BILLING_URL` | `https://staterbill.com,https://www.staterbill.com` |
     | frontend-ai | `VITE_API_URL` | `https://staterbill-api-1076771386585.asia-south1.run.app` |
     | frontend-ai | `VITE_BILLING_URL` | `https://staterbill.com,https://www.staterbill.com` |
     | frontend-admin | `VITE_API_URL` | `https://staterbill-api-1076771386585.asia-south1.run.app` |
     | frontend-admin | `VITE_BILLING_URL` | `https://staterbill.com,https://www.staterbill.com` |

   - (d) Redeploy each project: Deployments → latest production deployment → ⋯ → Redeploy. Verify: `curl.exe -s https://<host>/build-info.json` on `staterbill.com`, `bizassist-task.vercel.app`, `bizassist-dev-workspace-ai.vercel.app` and the admin console's host shows that project's values from the table.
   - Rollback: promote the previous production deployment (Deployments → ⋯ → Instant Rollback).

6. Desktop release
   - Command: build and publish the installer through the existing release workflow, `.github/workflows/release.yml`.
   - Verify on an installed app, signed in as the owner: Settings shows the sync status from `GET http://127.0.0.1:8001/api/sync/status`, with `cloud_url` = `https://staterbill-api-1076771386585.asia-south1.run.app`.

7. Decisions, each with its current default
   - `--min-instances 1` on `staterbill-api` removes cold starts but costs an always-on instance. Default: 0. To adopt: `gcloud run services update staterbill-api --project staterbill --region asia-south1 --min-instances 1`. Verify: `gcloud run services describe staterbill-api --project staterbill --region asia-south1` shows min instances 1.
   - `SUBSCRIPTION_ENFORCED`. Default: 0. To enforce: `.\backend\deploy_cloudrun.ps1 -Project staterbill -SubscriptionEnforced 1`. Verify: the same `describe` command shows `SUBSCRIPTION_ENFORCED=1`.
   - `team.staterbill.com` and `ai.staterbill.com`. Default: not adopted. To adopt one: add its DNS record and the domain in the Vercel project, add the new origin to the APIs' CORS and trust settings (for the Field Team API, the `-AllowedOrigins` value from step 1), and point `VITE_FIELD_TEAM_URL` or `VITE_AI_DASHBOARD_URL` from step 5 (c) at it. Verify: `curl.exe -sI https://team.staterbill.com` (or `ai.staterbill.com`) returns 200 with no certificate error.
   - Retiring the Hugging Face Space. Default: keep it until installed desktop apps have updated (design assumption 6).

8. Release check and smoke test
   - Command: `python dev/check_cloud_release.py --report release-report.json`. Expected: every check passes, and `release-report.json` records the results.
   - Then check by hand:
     - web sign-in on a phone, including a cold start;
     - Field Team opened from https://staterbill.com signs in as the right business;
     - Dashboard → BIZASSIST opens the AI dashboard with no Vercel page;
     - the admin console's Infrastructure page shows real values or "unavailable";
     - desktop sync status shows the Cloud Run URL and the outbox drains;
     - a web tab left open for more than 5 minutes shows no sync toasts and no sign-out.
