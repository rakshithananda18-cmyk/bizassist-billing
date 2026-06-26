<#
  run_tests.ps1 - run the backend (pytest) and/or frontend (vitest) test suites.

  Usage:
    .\run_tests.ps1            # both suites
    .\run_tests.ps1 backend    # backend only
    .\run_tests.ps1 frontend   # frontend only

  Or double-click run_tests.bat.

  NOTE: test-only env vars (mock GROQ key etc.) are set ONLY if missing and are
  removed again at the end, so they never leak into your shell / the dev server.
#>
param(
    [ValidateSet("all", "backend", "frontend")]
    [string]$Only = "all"
)

$root = $PSScriptRoot
$backendExit = 0
$frontendExit = 0
$srvProcess = $null

# --- Clean up any stale dashboard servers ---
Get-CimInstance Win32_Process -Filter "CommandLine like '%serve_dashboard.py%'" -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

# --- Launch the live Web visibility dashboard in the background ---
$python = Join-Path $root "venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}
$urlFile = Join-Path $root "dashboard_url.txt"
if (Test-Path $urlFile) { Remove-Item $urlFile }

Write-Host "Launching live Web visibility dashboard..." -ForegroundColor Green
$srvScript = Join-Path $root "serve_dashboard.py"
$srvProcess = Start-Process -FilePath $python -ArgumentList "`"$srvScript`"" -NoNewWindow -PassThru

# Wait for server port allocation handshake
$dashboardUrl = ""
for ($i = 0; $i -lt 10; $i++) {
    if (Test-Path $urlFile) {
        $dashboardUrl = Get-Content $urlFile -Raw
        Remove-Item $urlFile
        break
    }
    Start-Sleep -Milliseconds 500
}

if ($dashboardUrl) {
    Write-Host "--------------------------------------------------------" -ForegroundColor Green
    Write-Host "  BIZASSIST LIVE TEST DASHBOARD ACTIVE                  " -ForegroundColor Green
    Write-Host "  URL: $dashboardUrl" -ForegroundColor Cyan
    Write-Host "--------------------------------------------------------" -ForegroundColor Green
} else {
    Write-Host "Dashboard server started in background." -ForegroundColor Yellow
}

# Set test fallbacks ONLY if absent, and remember so we can remove them after
# (prevents the mock GROQ key leaking into start_dev and 401-ing the real server).
$cleanupJwt  = $false
$cleanupGroq = $false
if (-not $env:JWT_SECRET)   { $env:JWT_SECRET   = "dev-test-secret-please-change-0123456789abcdef"; $cleanupJwt  = $true }
if (-not $env:GROQ_API_KEY) { $env:GROQ_API_KEY = "mock_groq_api_key";                              $cleanupGroq = $true }

try {
    # --- Backend ------------------------------------------------------------
    if ($Only -eq "all" -or $Only -eq "backend") {
        Write-Host ""
        Write-Host "=== Backend tests (pytest) ===" -ForegroundColor Cyan
        $python = Join-Path $root "venv\Scripts\python.exe"
        if (-not (Test-Path $python)) {
            Write-Host "venv python not found, using 'python' on PATH" -ForegroundColor Yellow
            $python = "python"
        }
        Push-Location (Join-Path $root "backend")
        & $python -m pytest tests/ -q
        $backendExit = $LASTEXITCODE
        Pop-Location
    }

    # --- Frontend (both apps: billing = canonical, ai = the AI dashboard) ----
    if ($Only -eq "all" -or $Only -eq "frontend") {
        foreach ($fe in @("frontend-billing", "frontend-ai")) {
            $fePath = Join-Path $root $fe
            if (-not (Test-Path $fePath)) { continue }
            Write-Host ""
            Write-Host "=== Frontend tests (vitest) - $fe ===" -ForegroundColor Cyan
            Push-Location $fePath
            if (-not (Test-Path "node_modules")) {
                Write-Host "Installing $fe dependencies (first run only)..." -ForegroundColor Yellow
                npm install
            }
            npm test
            if ($LASTEXITCODE -ne 0) { $frontendExit = $LASTEXITCODE }
            Pop-Location
        }
    }
}
finally {
    # Remove the fallbacks we added, so nothing leaks into this shell.
    if ($cleanupJwt)  { Remove-Item Env:\JWT_SECRET   -ErrorAction SilentlyContinue }
    if ($cleanupGroq) { Remove-Item Env:\GROQ_API_KEY -ErrorAction SilentlyContinue }
}

# --- Summary ----------------------------------------------------------------
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
if ($backendExit -ne 0 -or $frontendExit -ne 0) {
    Write-Host "Some tests FAILED." -ForegroundColor Red
} else {
    Write-Host "All tests passed." -ForegroundColor Green
}

# --- Wait for user input to keep server running ---
Write-Host ""
Write-Host "========================================================" -ForegroundColor Green
Write-Host "  Dashboard is running live.                            " -ForegroundColor Green
Write-Host "  Press Enter in this window to stop server and exit... " -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Green
Read-Host

if ($srvProcess) {
    Stop-Process -Id $srvProcess.Id -Force -ErrorAction SilentlyContinue
}

if ($backendExit -ne 0 -or $frontendExit -ne 0) {
    exit 1
}
exit 0
