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
    [string]$AllowedOrigins = "https://staterbill.com,https://www.staterbill.com,https://admin.staterbill.com,https://bizassist-billing.vercel.app,http://localhost:5174",
    [int]$MinInstances = 0,
    [switch]$Setup,
    [switch]$ResetSecrets
)

$repo = (git -C $PSScriptRoot rev-parse --show-toplevel).Trim()
Push-Location $repo
$runSa = "$Service-run@$Project.iam.gserviceaccount.com"

function Invoke-Gcloud {
    & gcloud @args
    if ($LASTEXITCODE -ne 0) { throw "gcloud $($args -join ' ') failed ($LASTEXITCODE)" }
}

function Set-SecretValue([string]$Name, [string]$Value) {
    $tmp = [IO.Path]::GetTempFileName()
    try {
        [IO.File]::WriteAllText($tmp, $Value)
        $exists = (& gcloud secrets describe $Name --project $Project --format "value(name)" 2>$null)
        if ($exists) { Invoke-Gcloud secrets versions add $Name --project $Project --data-file $tmp }
        else { Invoke-Gcloud secrets create $Name --project $Project --replication-policy automatic --data-file $tmp }
    }
    finally { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
}

function Test-Secret([string]$Name) {
    return [bool](& gcloud secrets describe $Name --project $Project --format "value(name)" 2>$null)
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
            secretmanager.googleapis.com iam.googleapis.com compute.googleapis.com --project $Project

        $saExists = (& gcloud iam service-accounts describe $runSa --project $Project --format "value(email)" 2>$null)
        if (-not $saExists) {
            Write-Host "== Creating Service Account $runSa..." -ForegroundColor Cyan
            Invoke-Gcloud iam service-accounts create "$Service-run" --project $Project --display-name "STATER Bill API (Cloud Run)"
        }

        $number = (& gcloud projects describe $Project --format "value(projectNumber)").Trim()
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

        foreach ($s in @("DATABASE_URL", "JWT_SECRET", "GROQ_API_KEY")) {
            if (Test-Secret $s) {
                Invoke-Gcloud secrets add-iam-policy-binding $s --project $Project `
                    --member "serviceAccount:$runSa" --role roles/secretmanager.secretAccessor --quiet | Out-Null
            }
        }
        Write-Host "   [OK] Service account granted access to secrets." -ForegroundColor Green
    }

    Write-Host "== Building and Deploying $Service to Cloud Run..." -ForegroundColor Cyan
    $envVars = "^;^ADMIN_API_ENABLED=1;TZ=Asia/Kolkata;BIZ_TIMEZONE=Asia/Kolkata;WEB_CONCURRENCY=1;ALLOWED_ORIGINS=$AllowedOrigins"

    $secretsFlag = "DATABASE_URL=DATABASE_URL:latest,JWT_SECRET=JWT_SECRET:latest"
    if (Test-Secret "GROQ_API_KEY") {
        $secretsFlag += ",GROQ_API_KEY=GROQ_API_KEY:latest"
    }

    for ($attempt = 1; ; $attempt++) {
        & gcloud run deploy $Service --project $Project --region $Region --source backend `
            --service-account $runSa `
            --allow-unauthenticated --min-instances $MinInstances --max-instances 2 --cpu 1 --memory 1Gi `
            --cpu-boost --concurrency 80 --timeout 120 `
            --update-env-vars $envVars `
            --set-secrets $secretsFlag `
            --quiet
        if ($LASTEXITCODE -eq 0) { break }
        if ($attempt -ge 3) { throw "gcloud run deploy failed after $attempt attempts." }
        Write-Host "Deploy attempt $attempt failed; waiting 30s for IAM propagation..." -ForegroundColor Yellow
        Start-Sleep -Seconds 30
    }

    $url = (& gcloud run services describe $Service --project $Project --region $Region --format "value(status.url)").Trim()
    Write-Host "==========================================================" -ForegroundColor Green
    Write-Host " STATER Bill Backend is LIVE on Cloud Run (Mumbai)!        " -ForegroundColor Green
    Write-Host " URL: $url                                                " -ForegroundColor Green
    Write-Host "==========================================================" -ForegroundColor Green

    Write-Host "== Running health verification..." -ForegroundColor Cyan
    try {
        $root = Invoke-RestMethod "$url/" -TimeoutSec 30
        Write-Host "   Root Response: $($root.message)" -ForegroundColor Green
    } catch {
        Write-Host "   Warning: Health check timed out or failed: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}
finally {
    Pop-Location
}
