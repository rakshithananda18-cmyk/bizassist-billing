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

    # --- Frontend -----------------------------------------------------------
    if ($Only -eq "all" -or $Only -eq "frontend") {
        Write-Host ""
        Write-Host "=== Frontend tests (vitest) ===" -ForegroundColor Cyan
        Push-Location (Join-Path $root "frontend-react")
        if (-not (Test-Path "node_modules")) {
            Write-Host "Installing frontend dependencies (first run only)..." -ForegroundColor Yellow
            npm install
        }
        npm test
        $frontendExit = $LASTEXITCODE
        Pop-Location
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

if ($backendExit -ne 0 -or $frontendExit -ne 0) {
    Write-Host "Some tests FAILED." -ForegroundColor Red
    exit 1
}
Write-Host "All tests passed." -ForegroundColor Green
