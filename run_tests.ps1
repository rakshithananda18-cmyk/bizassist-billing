<#
  run_tests.ps1 - run the backend (pytest) and/or frontend (vitest) suites.
  Same commands and behaviour as bizassist-billing\run_tests.ps1.

  Usage:
    .\run_tests.ps1                  # both suites (serial)
    .\run_tests.ps1 backend          # backend only
    .\run_tests.ps1 frontend         # frontend only
    .\run_tests.ps1 all -Fast        # parallel backend (pytest-xdist, all CPU cores)
    .\run_tests.ps1 backend -Fast    # parallel backend only
    .\run_tests.ps1 all -Fast -NoDashboard   # no live dashboard, no "press Enter" (CI, scripts)

  Or double-click run_tests.bat (append 'fast' to go parallel:
    run_tests.bat backend fast).

  -Fast runs the backend suite across all CPU cores with pytest-xdist. Each
  worker is its own process with its own temp SQLite file (tests/conftest.py),
  so runs stay isolated. Without pytest-xdist it says so and runs serial:
    .venv\Scripts\python -m pip install -r backend\requirements-dev.txt

  Results stream into test_results.json (same schema as billing), which the
  live dashboard (serve_dashboard.py) shows while the run is in progress.
#>
param(
    [ValidateSet("all", "backend", "frontend")]
    [string]$Only = "all",
    [switch]$Fast,
    [switch]$NoDashboard
)

$root = $PSScriptRoot
$backendExit = 0
$frontendExit = 0
$srvProcess = $null

# --- Python: this repo's .venv, else venv, else PATH -----------------------
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = Join-Path $root "venv\Scripts\python.exe" }
if (-not (Test-Path $python)) {
    Write-Host ".venv python not found, using 'python' on PATH" -ForegroundColor Yellow
    $python = "python"
}

# --- Live dashboard (unless -NoDashboard) -----------------------------------
$results = Join-Path $root "test_results.json"
if (Test-Path $results) { Remove-Item $results -ErrorAction SilentlyContinue }
if (-not $NoDashboard) {
    Get-CimInstance Win32_Process -Filter "CommandLine like '%bizassist-task%serve_dashboard.py%'" -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    $urlFile = Join-Path $root "dashboard_url.txt"
    if (Test-Path $urlFile) { Remove-Item $urlFile }
    Write-Host "Launching live test dashboard..." -ForegroundColor Green
    $srvProcess = Start-Process -FilePath $python -ArgumentList "`"$(Join-Path $root 'serve_dashboard.py')`"" -NoNewWindow -PassThru
    $dashboardUrl = ""
    for ($i = 0; $i -lt 10; $i++) {
        if (Test-Path $urlFile) { $dashboardUrl = Get-Content $urlFile -Raw; Remove-Item $urlFile; break }
        Start-Sleep -Milliseconds 500
    }
    if ($dashboardUrl) {
        Write-Host "--------------------------------------------------------" -ForegroundColor Green
        Write-Host "  FIELD TEAM LIVE TEST DASHBOARD: $dashboardUrl" -ForegroundColor Cyan
        Write-Host "--------------------------------------------------------" -ForegroundColor Green
    }
}

# --- Backend -----------------------------------------------------------------
if ($Only -eq "all" -or $Only -eq "backend") {
    Write-Host ""
    Write-Host "=== Backend tests (pytest) ===" -ForegroundColor Cyan
    Push-Location (Join-Path $root "backend")
    # --dist loadscope keeps a whole test FILE on one worker, so the app boot +
    # migration (the dominant per-file cost) is paid once per file.
    $pytestArgs = @("tests/", "-q")
    if ($Fast) {
        & $python -c "import xdist" 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Fast mode: parallel across all CPU cores (pytest-xdist)." -ForegroundColor Green
            $pytestArgs += @("-n", "auto", "--dist", "loadscope")
        } else {
            Write-Host "Fast mode requested but pytest-xdist is not installed - running serial." -ForegroundColor Yellow
            Write-Host "  Install it once with:  .venv\Scripts\python -m pip install pytest-xdist" -ForegroundColor Yellow
        }
    }
    & $python -m pytest @pytestArgs
    $backendExit = $LASTEXITCODE
    Pop-Location
}

# --- Frontend ----------------------------------------------------------------
if ($Only -eq "all" -or $Only -eq "frontend") {
    Write-Host ""
    Write-Host "=== Frontend tests (vitest) - frontend ===" -ForegroundColor Cyan
    Push-Location (Join-Path $root "frontend")
    if (-not (Test-Path "node_modules")) {
        Write-Host "Installing frontend dependencies (first run only)..." -ForegroundColor Yellow
        npm install
    }
    if ($Fast) {
        $cores = [Environment]::ProcessorCount
        Write-Host "Fast mode: vitest across $cores thread(s)." -ForegroundColor Green
        npx vitest run --pool=threads --poolOptions.threads.maxThreads=$cores --reporter=dot
    } else {
        npm test
    }
    if ($LASTEXITCODE -ne 0) { $frontendExit = $LASTEXITCODE }
    Pop-Location
}

# --- Summary -------------------------------------------------------------------
Write-Host ""
Write-Host "---------------- Summary ----------------" -ForegroundColor Cyan
if ($Only -ne "frontend") {
    if ($backendExit -eq 0) { Write-Host "backend : PASS" -ForegroundColor Green }
    else                    { Write-Host "backend : FAIL ($backendExit)" -ForegroundColor Red }
}
if ($Only -ne "backend") {
    if ($frontendExit -eq 0) { Write-Host "frontend: PASS" -ForegroundColor Green }
    else                     { Write-Host "frontend: FAIL ($frontendExit)" -ForegroundColor Red }
}
Write-Host ""
if ($backendExit -ne 0 -or $frontendExit -ne 0) { Write-Host "Some tests FAILED." -ForegroundColor Red }
else                                             { Write-Host "All tests passed." -ForegroundColor Green }

# --- Keep the dashboard up until Enter (interactive runs only) -----------------
if ($srvProcess) {
    if (-not [Console]::IsInputRedirected) {
        Write-Host ""
        Write-Host "Dashboard is still running. Press Enter to stop it and exit..." -ForegroundColor Green
        Read-Host | Out-Null
    }
    Stop-Process -Id $srvProcess.Id -Force -ErrorAction SilentlyContinue
}

if ($backendExit -ne 0 -or $frontendExit -ne 0) { exit 1 }
exit 0
