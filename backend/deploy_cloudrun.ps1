<#
  deploy_cloudrun.ps1 — Deploy STATER Bill Core Backend to Google Cloud Run (Mumbai / asia-south1).

  Prerequisites:
    1. Google Cloud CLI installed & authenticated: gcloud auth login
    2. Run from the repo root:
       .\backend\deploy_cloudrun.ps1 -Project staterbill -Setup
#>
param(
    [Parameter(Mandatory = $false)][string]$Project = "staterbill",
    [string]$Region = "asia-south1",
    [string]$Service = "staterbill-api",
    [string]$AllowedOrigins = "https://staterbill.com,https://www.staterbill.com,https://admin.staterbill.com,https://bizassist-billing.vercel.app,https://bizassist-task.vercel.app,https://bizassist-dev-workspace-ai.vercel.app",
    [int]$MinInstances = 0,
    [ValidateSet('0','1')][string]$SubscriptionEnforced = '0',
    [switch]$Setup,
    [switch]$ResetSecrets
)
$ErrorActionPreference = 'Stop'

$repo = (git -C $PSScriptRoot rev-parse --show-toplevel).Trim()
Push-Location $repo
$runSa = "$Service-run@$Project.iam.gserviceaccount.com"

function Invoke-Gcloud {
    & gcloud @args
    if ($LASTEXITCODE -ne 0) { throw "gcloud operation failed ($LASTEXITCODE)" }
}

function Get-GcloudOptional {
    # Missing resources are normal during first deployment. Native stderr can
    # otherwise become a terminating error under the script's Stop preference.
    $ErrorActionPreference = 'Continue'
    $result = & gcloud @args 2>$null
    if ($LASTEXITCODE -eq 0) { return $result }
    return $null
}

function Invoke-GcloudQuiet {
    # Scheduler errors can echo request headers. Keep both native streams out
    # of the transcript and report only success/failure to the caller.
    $ErrorActionPreference = 'Continue'
    & gcloud @args 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Wait-RcHealth([string]$BaseUrl) {
    $deadline = [DateTime]::UtcNow.AddSeconds(120)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $health = Invoke-RestMethod "$BaseUrl/health" -TimeoutSec 60
            if ($health.status -eq 'ok' -and $health.db -eq 'connected') { return $true }
        } catch { }
        Start-Sleep -Seconds 5
    }
    return $false
}

function Set-SecretValue([string]$Name, [string]$Value) {
    $tmp = [IO.Path]::GetTempFileName()
    try {
        [IO.File]::WriteAllText($tmp, $Value)
        $exists = Get-GcloudOptional secrets describe $Name --project $Project --format "value(name)"
        if ($exists) { Invoke-Gcloud secrets versions add $Name --project $Project --data-file $tmp }
        else { Invoke-Gcloud secrets create $Name --project $Project --replication-policy automatic --data-file $tmp }
    }
    finally { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
}

function Test-Secret([string]$Name) {
    return [bool](Get-GcloudOptional secrets describe $Name --project $Project --format "value(name)")
}

function Read-SecretValue([string]$Prompt) {
    $secure = Read-Host -AsSecureString -Prompt $Prompt
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

try {
    Write-Host "==========================================================" -ForegroundColor Cyan
    Write-Host " STATER Bill — Deploying Backend to Cloud Run ($Region)    " -ForegroundColor Cyan
    Write-Host " Project: $Project | Service: $Service                    " -ForegroundColor Cyan
    Write-Host "==========================================================" -ForegroundColor Cyan

    if ($Setup) {
        Write-Host "== Enabling Required Google Cloud APIs..." -ForegroundColor Cyan
        Invoke-Gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com `
            secretmanager.googleapis.com iam.googleapis.com compute.googleapis.com cloudscheduler.googleapis.com --project $Project

        $saExists = Get-GcloudOptional iam service-accounts describe $runSa --project $Project --format "value(email)"
        if (-not $saExists) {
            Write-Host "== Creating Service Account $runSa..." -ForegroundColor Cyan
            Invoke-Gcloud iam service-accounts create "$Service-run" --project $Project --display-name "STATER Bill API (Cloud Run)"
        }

        $number = (Invoke-Gcloud projects describe $Project --format "value(projectNumber)").Trim()
        $buildSa = "$number-compute@developer.gserviceaccount.com"
        Invoke-Gcloud projects add-iam-policy-binding $Project --member "serviceAccount:$buildSa" `
            --role roles/run.builder --condition None --quiet | Out-Null

        Write-Host "== Verifying Secrets in Secret Manager..." -ForegroundColor Cyan
        if ($ResetSecrets -or -not (Test-Secret "DATABASE_URL")) {
            Write-Host "   Enter DATABASE_URL (Supabase pooler URI):"
            Set-SecretValue "DATABASE_URL" (Read-SecretValue "DATABASE_URL")
        } else { Write-Host "   [OK] DATABASE_URL already present." -ForegroundColor Green }

        if ($ResetSecrets -or -not (Test-Secret "JWT_SECRET")) {
            Write-Host "   Enter JWT_SECRET (exact same key as existing auth):"
            Set-SecretValue "JWT_SECRET" (Read-SecretValue "JWT_SECRET")
        } else { Write-Host "   [OK] JWT_SECRET already present." -ForegroundColor Green }

        if ($ResetSecrets -or -not (Test-Secret "GROQ_API_KEY")) {
            Write-Host "   Enter GROQ_API_KEY (for AI features):"
            Set-SecretValue "GROQ_API_KEY" (Read-SecretValue "GROQ_API_KEY")
        } else { Write-Host "   [OK] GROQ_API_KEY already present." -ForegroundColor Green }

        if (-not (Test-Secret 'BILLING_CRON_SECRET')) {
            $bytes = New-Object byte[] 32
            $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
            try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
            Set-SecretValue 'BILLING_CRON_SECRET' (([BitConverter]::ToString($bytes) -replace '-', '').ToLower())
            [Array]::Clear($bytes, 0, $bytes.Length)
        }

        foreach ($s in @("DATABASE_URL", "JWT_SECRET", "GROQ_API_KEY", "BILLING_CRON_SECRET", "ADMIN_SERVICE_URL")) {
            if (Test-Secret $s) {
                Invoke-Gcloud secrets add-iam-policy-binding $s --project $Project `
                    --member "serviceAccount:$runSa" --role roles/secretmanager.secretAccessor --quiet | Out-Null
            }
        }
        Write-Host "   [OK] Service account granted access to secrets." -ForegroundColor Green
    }

    Write-Host "== Building and Deploying $Service to Cloud Run..." -ForegroundColor Cyan
    if (-not (Test-Secret 'BILLING_CRON_SECRET')) { throw 'BILLING_CRON_SECRET is missing; run with -Setup first.' }
    $envVars = "^;^ADMIN_API_ENABLED=1;TZ=Asia/Kolkata;BIZ_TIMEZONE=Asia/Kolkata;WEB_CONCURRENCY=1;SUBSCRIPTION_ENFORCED=$SubscriptionEnforced;CLOUD_RUN_REGION=$Region;SSE_MAX_STREAM_SECONDS=100;ALLOWED_ORIGINS=$AllowedOrigins"

    $secretsFlag = "DATABASE_URL=DATABASE_URL:latest,JWT_SECRET=JWT_SECRET:latest,BILLING_CRON_SECRET=BILLING_CRON_SECRET:latest"
    if (Test-Secret "GROQ_API_KEY") {
        $secretsFlag += ",GROQ_API_KEY=GROQ_API_KEY:latest"
    }
    if (Test-Secret 'ADMIN_SERVICE_URL') {
        $secretsFlag += ',ADMIN_SERVICE_URL=ADMIN_SERVICE_URL:latest'
    } else { Write-Host 'ADMIN_SERVICE_URL is not mounted; a constrained runtime needs it for the admin console.' }
    $existing = Get-GcloudOptional run services describe $Service --project $Project --region $Region --format 'value(status.url)'
    $rolloutFlags = @()
    if ($existing) { $rolloutFlags = @('--no-traffic', '--tag', 'candidate') }

    for ($attempt = 1; ; $attempt++) {
        # --max-instances 1: events/rate limits are process-local; scaling requires shared event delivery.
        & gcloud run deploy $Service --project $Project --region $Region --source backend @rolloutFlags `
            --service-account $runSa `
            --allow-unauthenticated --min-instances $MinInstances --max-instances 1 --port 8080 --cpu 1 --memory 1Gi `
            --cpu-boost --concurrency 80 --timeout 120 `
            --update-env-vars $envVars `
            --update-secrets $secretsFlag `
            --quiet
        if ($LASTEXITCODE -eq 0) { break }
        if ($attempt -ge 3) { throw "gcloud run deploy failed after $attempt attempts." }
        Write-Host "Deploy attempt $attempt failed; waiting 30s for IAM propagation..." -ForegroundColor Yellow
        Start-Sleep -Seconds 30
    }

    $description = (Invoke-Gcloud run services describe $Service --project $Project --region $Region --format json) | ConvertFrom-Json
    $url = $description.status.url
    $probeUrl = $url
    if ($existing) {
        $probeUrl = ($description.status.traffic | Where-Object { $_.tag -eq 'candidate' } | Select-Object -First 1).url
        if (-not $probeUrl) { throw 'Release candidate tag URL is missing; traffic was not moved.' }
    }
    if (-not (Wait-RcHealth $probeUrl)) {
        Write-Error "Health verification failed for $($description.status.latestCreatedRevisionName); traffic was not moved." -ErrorAction Continue
        exit 1
    }
    if ($existing) { Invoke-Gcloud run services update-traffic $Service --project $Project --region $Region --to-latest --quiet }

    if ($Setup) {
        $cronSecret = (Invoke-Gcloud secrets versions access latest --secret BILLING_CRON_SECRET --project $Project).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $cronSecret) { throw 'Could not load the Scheduler credential.' }
        try {
            foreach ($entry in (Get-Content -LiteralPath "$repo/ops/cloud-scheduler-jobs.json" -Raw | ConvertFrom-Json)) {
                $jobName = "$Service-$($entry.job -replace '_','-')"
                $jobExists = Get-GcloudOptional scheduler jobs describe $jobName --project $Project --location $Region --format 'value(name)'
                $verb = if ($jobExists) { 'update' } else { 'create' }
                $headerFlag = if ($jobExists) { '--update-headers' } else { '--headers' }
                $schedulerArgs = @('scheduler','jobs',$verb,'http',$jobName,'--project',$Project,'--location',$Region,
                    '--schedule',$entry.schedule,'--uri',"$url/internal/cron/$($entry.job)",'--http-method','POST',
                    '--time-zone','Asia/Kolkata','--attempt-deadline','120s','--max-retry-attempts','5','--min-backoff','30s',
                    $headerFlag,"X-Cron-Secret=$cronSecret",'--format','value(name)','--quiet')
                if (-not (Invoke-GcloudQuiet @schedulerArgs)) { throw "Scheduler setup failed for $jobName" }
            }
        } finally { Remove-Variable cronSecret, schedulerArgs -ErrorAction SilentlyContinue }
    }
    Write-Host "==========================================================" -ForegroundColor Green
    Write-Host " STATER Bill Backend is LIVE on Cloud Run (Mumbai)!        " -ForegroundColor Green
    Write-Host " URL: $url                                                " -ForegroundColor Green
    Write-Host "==========================================================" -ForegroundColor Green

}
finally {
    Pop-Location
}
