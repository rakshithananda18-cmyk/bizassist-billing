<#
  deploy_cloudrun.ps1 - deploy backend-task/ (the Field Team API) to Google
  Cloud Run in Mumbai (asia-south1).

  Needs the Google Cloud CLI, signed in once:   gcloud auth login
  Run from the repo root, normally on an up-to-date main.

    # first time: enable APIs, store secrets (you type them; nothing is
    # printed), grant access, deploy, and schedule the daily GPS purge
    .\backend-task\deploy_cloudrun.ps1 -Project <your-project-id> -Setup

    # every later deploy (Cloud Build builds backend-task/Dockerfile)
    .\backend-task\deploy_cloudrun.ps1 -Project <your-project-id>

    # once the Vercel URL exists (kept on later deploys until changed)
    .\backend-task\deploy_cloudrun.ps1 -Project <id> -AllowedOrigins https://<vercel-url>

  Service shape (docs/FIELD_TEAM_MASTER_PLAN.md section 8):
    - max 1 instance: login throttling is in-memory (one process, like billing)
    - min 0 instances: free tier; wakes in seconds (-MinInstances 1 = always
      warm, billed for idle time)
    - CPU only during requests, so the in-process purge loop is OFF
      (TASK_PURGE_LOOP=0); Cloud Scheduler calls the purge endpoint daily.
    - secrets in Secret Manager: DATABASE_URL, JWT_SECRET (billing's values),
      TASK_CRON_SECRET (generated here)
#>
param(
    [Parameter(Mandatory = $true)][string]$Project,
    [string]$Region = "asia-south1",
    [string]$Service = "bizassist-task",
    [string]$AllowedOrigins = "",
    [int]$MinInstances = 0,
    [switch]$Setup
)

# No global ErrorActionPreference=Stop: on Windows PowerShell 5.1 it turns a
# native command's ordinary stderr (gcloud's progress lines) into a failure.
# Every gcloud call checks its own exit code instead.
$repo = (git -C $PSScriptRoot rev-parse --show-toplevel).Trim()
Push-Location $repo
# The API runs as its own service account, allowed to read only its secrets.
$runSa = "$Service-run@$Project.iam.gserviceaccount.com"

function Invoke-Gcloud {
    # Run gcloud; stop on failure (native exit codes do not trip ErrorActionPreference).
    & gcloud @args
    if ($LASTEXITCODE -ne 0) { throw "gcloud $($args -join ' ') failed ($LASTEXITCODE)" }
}

function Set-SecretValue([string]$Name, [string]$Value) {
    # Written to a temp file WITHOUT a trailing newline: piping a string to
    # gcloud adds one, and JWT_SECRET must match billing's value byte for byte.
    $tmp = [IO.Path]::GetTempFileName()
    try {
        [IO.File]::WriteAllText($tmp, $Value)
        $exists = (& gcloud secrets describe $Name --project $Project --format "value(name)" 2>$null)
        if ($exists) { Invoke-Gcloud secrets versions add $Name --project $Project --data-file $tmp }
        else { Invoke-Gcloud secrets create $Name --project $Project --replication-policy automatic --data-file $tmp }
    }
    finally { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
}

function Read-SecretValue([string]$Prompt) {
    $secure = Read-Host -AsSecureString -Prompt $Prompt
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

try {
    $branch = (git rev-parse --abbrev-ref HEAD).Trim()
    if ($branch -ne "main") { Write-Host "Note: deploying from branch '$branch', not main." -ForegroundColor Yellow }
    if (git status --porcelain -- backend-task) {
        Write-Host "Uncommitted changes in backend-task/ WILL be deployed (gcloud uploads the folder as it is on disk)." -ForegroundColor Yellow
    }

    if ($Setup) {
        Write-Host "== Enabling APIs (Cloud Run, Cloud Build, Artifact Registry, Secret Manager, Cloud Scheduler, IAM, Compute)..." -ForegroundColor Cyan
        # Compute: source deploys build as the project's default compute account,
        # which a brand-new project only gets once this API is on.
        Invoke-Gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com `
            secretmanager.googleapis.com cloudscheduler.googleapis.com iam.googleapis.com compute.googleapis.com --project $Project

        $saExists = (& gcloud iam service-accounts describe $runSa --project $Project --format "value(email)" 2>$null)
        if (-not $saExists) {
            Invoke-Gcloud iam service-accounts create "$Service-run" --project $Project --display-name "Field Team API (Cloud Run)"
        }

        Write-Host "== Secrets (typed values are hidden and never printed)" -ForegroundColor Cyan
        Write-Host "   DATABASE_URL: the SAME Supabase string billing uses (use the pooler URI, host *.pooler.supabase.com)."
        Set-SecretValue "DATABASE_URL" (Read-SecretValue "DATABASE_URL")
        Write-Host "   JWT_SECRET: exactly billing's value."
        Set-SecretValue "JWT_SECRET" (Read-SecretValue "JWT_SECRET")
        $cron = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 48 | ForEach-Object { [char]$_ })
        Set-SecretValue "TASK_CRON_SECRET" $cron
        Write-Host "   TASK_CRON_SECRET generated." -ForegroundColor Green

        foreach ($s in @("DATABASE_URL", "JWT_SECRET", "TASK_CRON_SECRET")) {
            Invoke-Gcloud secrets add-iam-policy-binding $s --project $Project `
                --member "serviceAccount:$runSa" --role roles/secretmanager.secretAccessor --quiet | Out-Null
        }
        Write-Host "   $runSa can read the 3 secrets (and nothing else)." -ForegroundColor Green
    }

    Write-Host "== Deploying $Service to Cloud Run ($Region) - Cloud Build builds backend-task/Dockerfile..." -ForegroundColor Cyan
    $envVars = "^;^TASK_PURGE_LOOP=0;BIZ_TIMEZONE=Asia/Kolkata"
    if ($AllowedOrigins) { $envVars += ";ALLOWED_ORIGINS=$AllowedOrigins" }
    Invoke-Gcloud run deploy $Service --project $Project --region $Region --source backend-task `
        --service-account $runSa `
        --allow-unauthenticated --min-instances $MinInstances --max-instances 1 --cpu 1 --memory 512Mi `
        --cpu-boost --concurrency 80 --timeout 60 `
        --update-env-vars $envVars `
        --set-secrets "DATABASE_URL=DATABASE_URL:latest,JWT_SECRET=JWT_SECRET:latest,TASK_CRON_SECRET=TASK_CRON_SECRET:latest" `
        --quiet

    $url = (& gcloud run services describe $Service --project $Project --region $Region --format "value(status.url)").Trim()
    Write-Host "Service URL: $url" -ForegroundColor Green

    if ($Setup) {
        Write-Host "== Daily GPS purge (Cloud Scheduler, 03:30 IST)..." -ForegroundColor Cyan
        $cronSecret = (& gcloud secrets versions access latest --secret TASK_CRON_SECRET --project $Project)
        $job = "$Service-purge-pings"
        $exists = (& gcloud scheduler jobs describe $job --project $Project --location $Region --format "value(name)" 2>$null)
        $verb = if ($exists) { "update" } else { "create" }
        $headerFlag = if ($exists) { "--update-headers" } else { "--headers" }
        Invoke-Gcloud scheduler jobs $verb http $job --project $Project --location $Region `
            --schedule "30 3 * * *" --time-zone "Asia/Kolkata" --uri "$url/api/internal/purge-pings" `
            --http-method POST $headerFlag "X-Cron-Secret=$cronSecret" --attempt-deadline 300s --quiet | Out-Null
        Write-Host "   Scheduler job '$job' set." -ForegroundColor Green
    }

    Write-Host "== Health check" -ForegroundColor Cyan
    try { $health = Invoke-RestMethod "$url/api/health" -TimeoutSec 60 -ErrorAction Stop }
    catch { Write-Host "Health check failed: $($_.Exception.Message) - see Cloud Run > $Service > Logs." -ForegroundColor Red; exit 1 }
    $health | ConvertTo-Json -Compress | Write-Host
    if ($health.db -ne "postgresql") {
        Write-Host "WARNING: db is '$($health.db)', not postgresql - check the DATABASE_URL secret." -ForegroundColor Red
        exit 1
    }
    Write-Host "Field Team API is live on Supabase: $url" -ForegroundColor Green
}
finally {
    Pop-Location
}
