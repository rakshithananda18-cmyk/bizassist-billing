@echo off
REM ============================================================
REM  BizAssist Field Team - Dev Launcher (same pattern as billing)
REM  API:  http://127.0.0.1:8002   (uvicorn --reload, SQLite, standalone)
REM  PWA:  http://localhost:5176   (Vite; /api proxied to :8002)
REM  Log:  backend\logs\bizassist_task.log
REM
REM  First run: creates .venv, installs backend\requirements-dev.txt,
REM  and copies .env.example to backend\.env (local SQLite + a dev secret).
REM  Kills any stale process on 8002 / 5176 first, so a zombie backend
REM  never ignores your code changes.
REM ============================================================
setlocal
set ROOT=%~dp0

echo Cleaning up stale processes on ports 8002, 5176...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8002 " ^| findstr "LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5176 " ^| findstr "LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 /nobreak >nul

if not exist "%ROOT%.venv\Scripts\python.exe" (
    echo Creating .venv and installing backend dependencies...
    python -m venv "%ROOT%.venv"
    REM --prefer-binary: on an older Python the newest greenlet may ship no
    REM Windows wheel, and building it needs the MSVC build tools.
    "%ROOT%.venv\Scripts\python.exe" -m pip install --prefer-binary -r "%ROOT%backend\requirements-dev.txt"
)
if not exist "%ROOT%backend\.env" (
    echo No backend\.env - copying .env.example for local dev.
    copy "%ROOT%.env.example" "%ROOT%backend\.env" >nul
)

REM --- API (with --reload so code changes are picked up instantly) ---
start "BizAssist Task API" powershell -ExecutionPolicy Bypass -NoExit -Command ^
  "cd '%ROOT%backend'; & '%ROOT%.venv\Scripts\Activate.ps1'; $env:LOG_FILE='logs/bizassist_task.log'; Write-Host 'Field Team API -> http://127.0.0.1:8002' -ForegroundColor Green; uvicorn app.main:app --reload --port 8002"

REM Give the API a moment to bind the port before the PWA starts
timeout /t 3 /nobreak >nul

REM --- PWA ---
start "BizAssist Task PWA" powershell -ExecutionPolicy Bypass -NoExit -Command ^
  "cd '%ROOT%frontend'; if (-not (Test-Path 'node_modules')) { npm install }; Write-Host 'Field Team PWA -> http://localhost:5176' -ForegroundColor Cyan; npm run dev -- --port 5176"

echo.
echo  Started:
echo   - Field Team API on :8002  (with --reload, log: backend\logs\bizassist_task.log)
echo   - Field Team PWA on :5176
echo  Close the opened windows to stop.
echo.
