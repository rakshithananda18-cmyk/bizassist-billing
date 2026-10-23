<#
  dev/dev_env.ps1 - settings for start_dev.bat's windows (dot-sourced by them).

    . dev\dev_env.ps1 -App task                 # Field Team API, normal dev
    . dev\dev_env.ps1 -App billing -FieldTest   # billing backend, field test mode

  Every mode: Field Team uses billing's JWT_SECRET (backend\.env), as in the
  cloud, where both services read one secret - a billing session or sign-in
  ticket is valid in Field Team.

  -FieldTest (start_dev.bat fieldtest): billing and Field Team share ONE
  throwaway database, local_field_test.db in the repo folder - like the cloud's
  one Supabase - so the whole billing <-> Field Team flow works locally.
  Nothing from it may reach production: every cloud address billing uses
  (sync, sign-up, plan checks, realtime, telemetry) points at a closed local
  port, so those calls fail at once, on this machine.
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

if ($App -eq "task") {
    $secret = Get-BillingSetting "JWT_SECRET"
    if ($secret) { $env:JWT_SECRET = $secret }
    else { Write-Host "backend\.env has no JWT_SECRET - Field Team keeps its own, so billing sign-in will not carry over." -ForegroundColor Yellow }
}

if (-not $FieldTest) { return }

switch ($App) {
    "billing" {
        $env:DATABASE_URL = $testDb
        $env:CLOUD_API_URL = $noCloud        # sync worker, plan checks, B2B proxy
        $env:CLOUD_URL = $noCloud            # start-up cloud probe, realtime listener
        $env:BIZASSIST_CLOUD_URL = $noCloud  # telemetry relay
    }
    "task" {
        $env:DATABASE_URL = $testDb
        $env:TASK_CREATE_BILLING_MIRROR = "0"   # billing owns users/customers/invoices here, as in the cloud
        Write-Host "Waiting for the billing backend to create the test database..." -ForegroundColor DarkGray
        for ($i = 0; $i -lt 90; $i++) {
            try { Invoke-WebRequest "http://127.0.0.1:8001/health" -UseBasicParsing -TimeoutSec 2 | Out-Null; break }
            catch { Start-Sleep -Seconds 2 }
        }
    }
    "billing-ui" {
        $env:VITE_FIELD_TEAM_URL = "http://localhost:5176"
        $env:VITE_API_URL = $noCloud   # on localhost billing's screens sign up on "the cloud" first
    }
    "seed" {
        $env:BIZASSIST_FIELD_TEST = "1"   # dev/field_test_seed.py refuses to run without it
    }
}
Write-Host "FIELD TEST MODE - throwaway database local_field_test.db (delete it to start fresh)" -ForegroundColor Magenta
