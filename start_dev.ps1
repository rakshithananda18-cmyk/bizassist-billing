<#
  start_dev.ps1 - start the backend API and the frontend dev server, each in its
  own window.

  Usage:
    .\start_dev.ps1            # backend (INFO logs) + frontend
    .\start_dev.ps1 -Dbg       # backend with LOG_LEVEL=DEBUG + frontend

  Or double-click start_dev.bat.
  Backend:  http://127.0.0.1:8001   (the frontend's config.js expects 8001)
  Frontend: http://127.0.0.1:5173
#>
param([switch]$Dbg)

$root     = $PSScriptRoot
$logLevel = if ($Dbg) { "DEBUG" } else { "INFO" }

# --- Backend (uvicorn, with venv activated) ---------------------------------
$backendCmd = @"
cd '$root\backend'
& '$root\venv\Scripts\Activate.ps1'
`$env:LOG_LEVEL='$logLevel'
Write-Host 'Backend on http://127.0.0.1:8001  (LOG_LEVEL=$logLevel)' -ForegroundColor Green
uvicorn main_groq:app --reload --port 8001
"@
Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd

# --- Frontend (vite) --------------------------------------------------------
$frontendCmd = @"
cd '$root\frontend-react'
if (-not (Test-Path 'node_modules')) { npm install }
Write-Host 'Frontend on http://127.0.0.1:5173' -ForegroundColor Green
npm run dev
"@
Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd

Write-Host "Launched backend + frontend in separate windows. Close those windows to stop." -ForegroundColor Cyan
