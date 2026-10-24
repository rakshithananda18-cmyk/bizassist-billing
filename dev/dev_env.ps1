<#
  dev/dev_env.ps1 - settings for start_dev.bat's windows (dot-sourced by them).

    . dev\dev_env.ps1 -App task                 # Field Team API, normal dev
    . dev\dev_env.ps1 -App billing -FieldTest   # billing backend, field test mode

  Normal dev (start_dev.bat): Field Team runs on BILLING'S OWN local database
  with billing's JWT_SECRET (both from backend\.env), as in the cloud, where both
  services share one Supabase and one secret. So the billing owner signs in to
  Field Team as themselves, shops come from their billing customers, and
  billing's Field Team link signs them in. Field Team only ADDS its own ft_*
  tables there (billing's sync never sends them); before the first time, the
  file is backed up to backend\bizassist.before-field-team.db. If billing's
  DATABASE_URL is not a local SQLite file (say a server), Field Team keeps its
  own database instead - a local Field Team must never write to a server.

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

function Get-SharedBillingDb {
    # Billing's database as seen from backend-task\ (one folder over), or $null
    # when it is not a local SQLite file. Billing's own default: database/db.py.
    $url = Get-BillingSetting "DATABASE_URL"
    if (-not $url) { $url = "sqlite:///./bizassist.db" }
    if ($url -match '^sqlite:///\./(.+)$') {
        return @{ Url = "sqlite:///../backend/$($Matches[1])"; File = Join-Path $repo "backend\$($Matches[1])" }
    }
    if ($url -match '^sqlite:///([A-Za-z]:/.+)$') {
        return @{ Url = $url; File = $Matches[1] }
    }
    return $null
}

function Backup-BillingDbOnce([string]$File) {
    # One copy, before Field Team first adds its tables. SQLite's backup API
    # gives a consistent copy even while billing is writing.
    # Written to a .partial file and renamed only when complete, so a failed
    # copy never leaves an empty backup that would stop the next attempt. Both
    # names end in .db, which backend\.gitignore keeps out of git.
    $folder = Split-Path -Parent $File
    $backup = Join-Path $folder "bizassist.before-field-team.db"
    if ((Test-Path $backup) -or -not (Test-Path $File)) { return }
    $partial = Join-Path $folder "bizassist.before-field-team.partial.db"
    Remove-Item $partial -ErrorAction SilentlyContinue
    & python -c "import sqlite3, sys; s = sqlite3.connect(sys.argv[1]); d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" $File $partial
    if ($LASTEXITCODE -eq 0 -and (Test-Path $partial) -and (Get-Item $partial).Length -gt 0) {
        Move-Item $partial $backup
        Write-Host "Backed up billing's database to $backup (once, before Field Team's tables)" -ForegroundColor DarkGray
    }
    else {
        Remove-Item $partial -ErrorAction SilentlyContinue
        Write-Host "Could not back up billing's database - Field Team will still start; copy $File yourself if you want a backup." -ForegroundColor Yellow
    }
}

if ($App -eq "task") {
    $secret = Get-BillingSetting "JWT_SECRET"
    if ($secret) { $env:JWT_SECRET = $secret }
    else { Write-Host "backend\.env has no JWT_SECRET - Field Team keeps its own, so billing sign-in will not carry over." -ForegroundColor Yellow }

    if (-not $FieldTest) {
        $shared = Get-SharedBillingDb
        if ($shared) {
            Wait-ForBilling
            Backup-BillingDbOnce $shared.File
            $env:DATABASE_URL = $shared.Url
            $env:TASK_CREATE_BILLING_MIRROR = "0"   # billing owns users/customers/invoices, as in the cloud
            Write-Host "Field Team uses billing's local database: $($shared.File)" -ForegroundColor DarkGray
        }
        else {
            Write-Host "billing's DATABASE_URL is not a local SQLite file - Field Team keeps backend-task\.env's own database." -ForegroundColor Yellow
        }
    }
}

# Billing's sidebar link to Field Team (local PWA), in both modes.
if ($App -eq "billing-ui") { $env:VITE_FIELD_TEAM_URL = "http://localhost:5176" }

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
        $env:TASK_CREATE_BILLING_MIRROR = "0"
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
