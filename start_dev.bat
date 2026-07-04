@echo off
REM ============================================================
REM  BizAssist — Dev Launcher (All-in-One)
REM  Backend:          http://127.0.0.1:8001
REM  AI Dashboard:     http://127.0.0.1:5173
REM  Billing Frontend: http://127.0.0.1:5174
REM
REM  Kills any stale process on each port first so you never
REM  end up with a zombie backend that ignores code changes.
REM ============================================================
setlocal

set ROOT=%~dp0

REM --- Kill any stale process already using our ports ---
echo Cleaning up stale processes on ports 8001, 5173, 5174, 5175...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8001 " ^| findstr "LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173 " ^| findstr "LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5174 " ^| findstr "LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5175 " ^| findstr "LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 /nobreak >nul

REM --- Backend (with --reload so code changes are picked up instantly) ---
start "BizAssist Backend" powershell -ExecutionPolicy Bypass -NoExit -Command ^
  "cd '%ROOT%backend'; & '%ROOT%venv\Scripts\Activate.ps1'; $env:PYTHONPATH='.'; $env:LOG_FILE='logs/bizassist.log'; Write-Host 'Backend → http://127.0.0.1:8001' -ForegroundColor Green; uvicorn main_groq:app --reload --port 8001"

REM Give the backend a moment to bind the port before frontends start
timeout /t 3 /nobreak >nul

REM --- AI Dashboard Frontend ---
start "BizAssist AI Dashboard" powershell -ExecutionPolicy Bypass -NoExit -Command ^
  "cd '%ROOT%frontend-ai'; if (-not (Test-Path 'node_modules')) { npm install }; Write-Host 'AI Dashboard → http://127.0.0.1:5173' -ForegroundColor Cyan; npm run dev -- --port 5173"

REM --- Billing Frontend ---
start "BizAssist Billing" powershell -ExecutionPolicy Bypass -NoExit -Command ^
  "cd '%ROOT%frontend-billing'; if (-not (Test-Path 'node_modules')) { npm install }; Write-Host 'Billing App → http://127.0.0.1:5174' -ForegroundColor Yellow; npm run dev -- --port 5174"

REM --- Admin Dashboard Frontend ---
start "BizAssist Admin Console" powershell -ExecutionPolicy Bypass -NoExit -Command ^
  "cd '%ROOT%frontend-admin'; if (-not (Test-Path 'node_modules')) { npm install }; Write-Host 'Admin Console → http://127.0.0.1:5175' -ForegroundColor Magenta; npm run dev -- --port 5175"

echo.
echo  Started:
echo   - Backend on :8001  (with --reload)
echo   - AI Dashboard on :5173
echo   - Billing App on :5174
echo   - Admin Console on :5175
echo  Close the opened windows to stop.
echo.
