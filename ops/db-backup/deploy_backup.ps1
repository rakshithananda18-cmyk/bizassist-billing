<#
  deploy_backup.ps1 - nightly backup of the shared cloud database (billing +
  Field Team, one Supabase) to a private Cloud Storage bucket, in the same
  Google Cloud project as the Field Team API.

  Needs the Google Cloud CLI, signed in once (gcloud auth login), and the
  DATABASE_URL secret that backend-task\deploy_cloudrun.ps1 -Setup stored.
  Safe to re-run; each run redeploys the job from ops\db-backup.

    .\ops\db-backup\deploy_backup.ps1 -Project bizassist-task
    .\ops\db-backup\deploy_backup.ps1 -Project bizassist-task -RunNow   # and take one now

  What it sets up:
    - bucket gs://<project>-db-backups: Mumbai, private (public access
      prevented), copies deleted after -KeepDays (default 30)
    - service account <job>-sa: reads only the DATABASE_URL secret and may only
      ADD objects to that bucket (it cannot read, change or delete backups)
    - Cloud Run Job <job> (built by Cloud Build from ops\db-backup\Dockerfile)
    - Cloud Scheduler job <job>-nightly: runs it at -Schedule, India time
#>
param(
    [Parameter(Mandatory = $true)][string]$Project,
    [string]$Region = "asia-south1",
    [string]$Job = "bizassist-db-backup",
    [int]$KeepDays = 30,
    [string]$Schedule = "0 2 * * *",
    [switch]$RunNow
)

# No global ErrorActionPreference=Stop: on Windows PowerShell 5.1 it turns a
# native command's ordinary stderr (gcloud's progress lines) into a failure.
$repo = (git -C $PSScriptRoot rev-parse --show-toplevel).Trim()
Push-Location $repo
$bucket = "$Project-db-backups"
$sa = "$Job-sa@$Project.iam.gserviceaccount.com"

function Invoke-Gcloud {
    & gcloud @args
    if ($LASTEXITCODE -ne 0) { throw "gcloud $($args -join ' ') failed ($LASTEXITCODE)" }
}

try {
    if (-not (& gcloud secrets describe DATABASE_URL --project $Project --format "value(name)" 2>$null)) {
        throw "No DATABASE_URL secret in $Project - run backend-task\deploy_cloudrun.ps1 -Setup first."
    }
    Write-Host "== APIs (Cloud Run, Cloud Build, Cloud Scheduler, Cloud Storage)..." -ForegroundColor Cyan
    Invoke-Gcloud services enable run.googleapis.com cloudbuild.googleapis.com cloudscheduler.googleapis.com `
        storage.googleapis.com --project $Project

    Write-Host "== Bucket gs://$bucket (private, copies kept $KeepDays days)..." -ForegroundColor Cyan
    if (-not (& gcloud storage buckets describe "gs://$bucket" --project $Project --format "value(name)" 2>$null)) {
        Invoke-Gcloud storage buckets create "gs://$bucket" --project $Project --location $Region `
            --uniform-bucket-level-access --public-access-prevention
    }
    $rules = [IO.Path]::GetTempFileName()
    try {
        [IO.File]::WriteAllText($rules, "{`"rule`": [{`"action`": {`"type`": `"Delete`"}, `"condition`": {`"age`": $KeepDays}}]}")
        Invoke-Gcloud storage buckets update "gs://$bucket" --lifecycle-file $rules
    }
    finally { Remove-Item $rules -Force -ErrorAction SilentlyContinue }

    Write-Host "== Service account $sa..." -ForegroundColor Cyan
    if (-not (& gcloud iam service-accounts describe $sa --project $Project --format "value(email)" 2>$null)) {
        Invoke-Gcloud iam service-accounts create "$Job-sa" --project $Project --display-name "Database backup (Cloud Run Job)"
    }
    Invoke-Gcloud secrets add-iam-policy-binding DATABASE_URL --project $Project `
        --member "serviceAccount:$sa" --role roles/secretmanager.secretAccessor --quiet | Out-Null
    Invoke-Gcloud storage buckets add-iam-policy-binding "gs://$bucket" `
        --member "serviceAccount:$sa" --role roles/storage.objectCreator | Out-Null

    Write-Host "== Cloud Run Job $Job (Cloud Build builds ops\db-backup)..." -ForegroundColor Cyan
    Invoke-Gcloud run jobs deploy $Job --project $Project --region $Region --source ops/db-backup `
        --service-account $sa --set-secrets "DATABASE_URL=DATABASE_URL:latest" `
        --set-env-vars "BACKUP_BUCKET=$bucket" `
        --tasks 1 --max-retries 1 --task-timeout 1800s --memory 1Gi --cpu 1
    # Scheduler starts the job as the same account; it may only run this job.
    Invoke-Gcloud run jobs add-iam-policy-binding $Job --project $Project --region $Region `
        --member "serviceAccount:$sa" --role roles/run.invoker | Out-Null

    Write-Host "== Nightly schedule ($Schedule, Asia/Kolkata)..." -ForegroundColor Cyan
    $uri = "https://run.googleapis.com/v2/projects/$Project/locations/$Region/jobs/${Job}:run"
    $nightly = "$Job-nightly"
    $verb = if (& gcloud scheduler jobs describe $nightly --project $Project --location $Region --format "value(name)" 2>$null) { "update" } else { "create" }
    Invoke-Gcloud scheduler jobs $verb http $nightly --project $Project --location $Region `
        --schedule $Schedule --time-zone "Asia/Kolkata" --uri $uri --http-method POST `
        --oauth-service-account-email $sa --oauth-token-scope "https://www.googleapis.com/auth/cloud-platform"

    if ($RunNow) {
        Write-Host "== Taking a backup now..." -ForegroundColor Cyan
        Invoke-Gcloud run jobs execute $Job --project $Project --region $Region --wait
        & gcloud storage ls -l "gs://$bucket/**" | Select-Object -Last 3
    }
    Write-Host "Done. Backups: gs://$bucket (restore: ops\db-backup\README.md)" -ForegroundColor Green
}
finally { Pop-Location }
