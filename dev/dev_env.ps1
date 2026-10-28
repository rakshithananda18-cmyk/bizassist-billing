<#
  dev/dev_env.ps1 - settings for start_dev.bat's windows (dot-sourced by them).

    . dev\dev_env.ps1 -App task                 # Field Team API, normal dev
    . dev\dev_env.ps1 -App billing -FieldTest   # billing backend, field test mode

  Normal dev preserves the TWO independent local databases. Operational Field
  Team is a Pro, online workspace over Billing's shared CLOUD database; normal
  Billing navigation opens that cloud app. The local Field Team API is only a
  development fixture and is never silently repointed at Billing's data.

  -FieldTest (start_dev.bat fieldtest): billing and Field Team share ONE
  throwaway database, local_field_test.db in the repo folder, with sample data,
  so nothing touches your real data. Nothing from it may reach production:
  every cloud address billing uses (sync, sign-up, plan checks, realtime,
  telemetry) points at a closed local port, so those calls fail at once.
#>
param(
    [Parameter(Mandatory = $true)][ValidateSet("billing", "billing-ui", "task", "seed")][string]$App,
    [switch]$FieldTest
)

$repo = Split-Path -Parent $PSScriptRoot
$testDb = "sqlite:///../local_field_test.db"   # both backends run one folder below the repo root
$noCloud = "http://127.0.0.1:9"                 # nothing listens on port 9

function Get-BillingSetting([string]$Name) {
    $file = Join-Path $repo "backend\.env"
    if (-not (Test-Path $file)) { return $null }
    foreach ($line in Get-Content $file) {
        if ($line -match "^\s*$Name\s*=\s*(.*)$") { return $Matches[1].Trim().Trim('"').Trim("'") }
    }
    return $null
}

function Wait-ForBilling {
    # Billing creates and migrates its tables at start-up; let it finish first.
    Write-Host "Waiting for the billing backend..." -ForegroundColor DarkGray
    for ($i = 0; $i -lt 90; $i++) {
        try { Invoke-WebRequest "http://127.0.0.1:8001/health" -UseBasicParsing -TimeoutSec 2 | Out-Null; return }
        catch { Start-Sleep -Seconds 2 }
    }
}

# Standalone local API is an explicit development fixture on its OWN database.
# Never enable a Billing mirror when this developer configured PostgreSQL.
if ($App -eq "task" -and -not $FieldTest) {
    $taskDb = $env:DATABASE_URL
    if (-not $taskDb) {
        $taskEnv = Join-Path $repo "backend-task\.env"
        if (Test-Path -LiteralPath $taskEnv) {
            foreach ($taskLine in Get-Content -LiteralPath $taskEnv) {
                if ($taskLine -match '^\s*DATABASE_URL\s*=\s*(.*)$') {
                    $taskDb = $Matches[1].Trim().Trim('"').Trim("'")
                    break
                }
            }
        }
    }
    if (-not $taskDb -or $taskDb -match '^sqlite') { $env:TASK_CREATE_BILLING_MIRROR = "1" }
    else { $env:TASK_CREATE_BILLING_MIRROR = "0" }
}

if ($App -eq "task" -and $FieldTest) {
    $secret = Get-BillingSetting "JWT_SECRET"
    if (-not $secret) { throw "Field test needs backend\.env JWT_SECRET for its isolated handoff." }
    $env:JWT_SECRET = $secret
}

# Only the explicit throwaway field test opens a local Field Team fixture.
if ($App -eq "billing-ui") {
    if ($FieldTest) {
        $env:VITE_FIELD_TEAM_URL = "http://localhost:5176"
        $env:VITE_FIELD_TEAM_LOCAL_TEST = "1"
    } else {
        $env:VITE_FIELD_TEAM_URL = "https://bizassist-task.vercel.app"
        $env:VITE_FIELD_TEAM_LOCAL_TEST = "0"
    }
}

if (-not $FieldTest) { return }

switch ($App) {
    "billing" {
        $env:DATABASE_URL = $testDb
        $env:BIZASSIST_TESTING = "1"
        $env:CLOUD_API_URL = $noCloud        # sync worker, plan checks, B2B proxy
        $env:CLOUD_URL = $noCloud            # start-up cloud probe, realtime listener
        $env:BIZASSIST_CLOUD_URL = $noCloud  # telemetry relay
    }
    "task" {
        $env:DATABASE_URL = $testDb
        $env:TASK_CREATE_BILLING_MIRROR = "0"
        $env:TASK_ALLOW_SQLITE_TESTING = "1"
        Wait-ForBilling
    }
    "billing-ui" {
        $env:VITE_API_URL = $noCloud   # on localhost billing's screens sign up on "the cloud" first
    }
    "seed" {
        $env:BIZASSIST_FIELD_TEST = "1"   # dev/field_test_seed.py refuses to run without it
    }
}
Write-Host "FIELD TEST MODE - throwaway database local_field_test.db (delete it to start fresh)" -ForegroundColor Magenta
