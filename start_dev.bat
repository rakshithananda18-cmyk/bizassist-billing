@echo off
REM ============================================================
REM  BizAssist — Dev Launcher (All-in-One)
REM  Backend:          http://127.0.0.1:8001
REM  AI Dashboard:     http://127.0.0.1:5173
REM  Billing Frontend: http://127.0.0.1:5174
REM  Admin Console:    http://127.0.0.1:5175
REM  Field Team API:   http://127.0.0.1:8002  (backend-task, isolated development fixture)
REM  Field Team PWA:   http://localhost:5176  (frontend-task; /api proxied to :8002)
REM
REM  Kills any stale process on each port first so you never
REM  end up with a zombie backend that ignores code changes.
REM
REM  Operational Field Team is Pro-only and cloud-only. Online Billing and
REM  Field Team share PostgreSQL; normal development preserves the TWO local
REM  databases. Billing opens the cloud Field Team workspace. The local Task
REM  API/PWA is a development fixture with its own backend-task settings.
REM
REM  start_dev.bat fieldtest   FIELD TEST MODE: billing and Field Team share
REM    one throwaway database (local_field_test.db) like the cloud's one
REM    Supabase, so invoices, the sidebar sign-in and field collections can be
REM    tried end to end. backend\bizassist.db is not touched and nothing goes
REM    to the cloud. A setup window creates test accounts and sample bills.
REM    Run start_dev.bat again without "fieldtest" to go back.
REM ============================================================
setlocal

set ROOT=%~dp0
set "FT="
set "MODE=normal"
if /I "%~1"=="fieldtest" set "FT= -FieldTest"
if /I "%~1"=="fieldtest" set "MODE=fieldtest"
if "%MODE%"=="fieldtest" echo FIELD TEST MODE - throwaway database local_field_test.db

REM --- Kill any stale process already using our ports ---
echo Cleaning up stale processes on ports 8001, 8002, 5173, 5174, 5175, 5176...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8002 " ^| findstr "LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5176 " ^| findstr "LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
)
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
  "cd '%ROOT%backend'; & '%ROOT%venv\Scripts\Activate.ps1'; . '%ROOT%dev\dev_env.ps1' -App billing%FT%; $env:PYTHONPATH='.'; $env:LOG_FILE='logs/bizassist.log'; Write-Host 'Backend -> http://127.0.0.1:8001' -ForegroundColor Green; uvicorn main_groq:app --reload --port 8001"

REM Give the backend a moment to bind the port before frontends start
timeout /t 3 /nobreak >nul

REM The AI dashboard and admin console are not part of the field test.
if "%MODE%"=="fieldtest" goto :after_side_apps

REM --- AI Dashboard Frontend ---
start "BizAssist AI Dashboard" powershell -ExecutionPolicy Bypass -NoExit -Command ^
  "cd '%ROOT%frontend-ai'; if (-not (Test-Path 'node_modules')) { npm install }; Write-Host 'AI Dashboard -> http://127.0.0.1:5173' -ForegroundColor Cyan; npm run dev -- --port 5173"

REM --- Admin Dashboard Frontend ---
start "BizAssist Admin Console" powershell -ExecutionPolicy Bypass -NoExit -Command ^
  "cd '%ROOT%frontend-admin'; if (-not (Test-Path 'node_modules')) { npm install }; Write-Host 'Admin Console -> http://127.0.0.1:5175' -ForegroundColor Magenta; npm run dev -- --port 5175"

:after_side_apps

REM --- Billing Frontend ---
start "BizAssist Billing" powershell -ExecutionPolicy Bypass -NoExit -Command ^
  "cd '%ROOT%frontend-billing'; if (-not (Test-Path 'node_modules')) { npm install }; . '%ROOT%dev\dev_env.ps1' -App billing-ui%FT%; Write-Host 'Billing App -> http://127.0.0.1:5174' -ForegroundColor Yellow; npm run dev -- --port 5174"

REM --- Field Team API (backend-task; same venv - billing's requirements cover it) ---
if not exist "%ROOT%backend-task\.env" (
    echo No backend-task\.env - copying backend-task\.env.example for local dev.
    copy "%ROOT%backend-task\.env.example" "%ROOT%backend-task\.env" >nul
)
start "BizAssist Field Team API" powershell -ExecutionPolicy Bypass -NoExit -Command ^
  "cd '%ROOT%backend-task'; & '%ROOT%venv\Scripts\Activate.ps1'; . '%ROOT%dev\dev_env.ps1' -App task%FT%; $env:LOG_FILE='logs/bizassist_task.log'; Write-Host 'Field Team API -> http://127.0.0.1:8002' -ForegroundColor Green; uvicorn app.main:app --reload --port 8002"

REM --- Field Team PWA (frontend-task) ---
start "BizAssist Field Team PWA" powershell -ExecutionPolicy Bypass -NoExit -Command ^
  "cd '%ROOT%frontend-task'; if (-not (Test-Path 'node_modules')) { npm install }; Write-Host 'Field Team PWA -> http://localhost:5176' -ForegroundColor Cyan; npm run dev -- --port 5176"

if "%MODE%"=="fieldtest" goto :fieldtest_setup

echo.
echo  Started:
echo   - Backend on :8001  (with --reload)
echo   - AI Dashboard on :5173
echo   - Billing App on :5174
echo   - Admin Console on :5175
echo   - Field Team API on :8002  (with --reload, on billing's local database, log backend-task\logs\bizassist_task.log)
echo   - Field Team PWA on :5176  (http://localhost:5176)
echo  Close the opened windows to stop.
echo.
goto :eof

:fieldtest_setup
REM --- Test accounts and sample bills, once both APIs are up ---
start "BizAssist Field Test Setup" powershell -ExecutionPolicy Bypass -NoExit -Command ^
  "cd '%ROOT%'; & '%ROOT%venv\Scripts\Activate.ps1'; . '%ROOT%dev\dev_env.ps1' -App seed -FieldTest; python dev\field_test_seed.py"

echo.
echo  FIELD TEST MODE started (throwaway database local_field_test.db):
echo   - Billing backend on :8001 and Billing App on :5174
echo   - Field Team API on :8002 and Field Team PWA on :5176
echo   - "Field Test Setup" window: test logins and what to try
echo  Run start_dev.bat (no "fieldtest") to go back to your normal data.
echo.
