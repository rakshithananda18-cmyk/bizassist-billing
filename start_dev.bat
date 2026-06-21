@echo off
REM ============================================================
REM  BizAssist — Dev Launcher (All-in-One)
REM  Backend:          http://127.0.0.1:8001
REM  AI Dashboard:     http://127.0.0.1:5173
REM  Billing Frontend: http://127.0.0.1:5174
REM ============================================================
setlocal

set ROOT=%~dp0

REM --- Backend ---
start "BizAssist Backend" powershell -ExecutionPolicy Bypass -NoExit -Command ^
  "cd '%ROOT%backend'; & '%ROOT%venv\Scripts\Activate.ps1'; Write-Host 'Backend → http://127.0.0.1:8001' -ForegroundColor Green; uvicorn main_groq:app --reload --port 8001"

REM --- AI Dashboard Frontend ---
start "BizAssist AI Dashboard" powershell -ExecutionPolicy Bypass -NoExit -Command ^
  "cd '%ROOT%frontend-ai'; if (-not (Test-Path 'node_modules')) { npm install }; Write-Host 'AI Dashboard → http://127.0.0.1:5173' -ForegroundColor Cyan; npm run dev -- --port 5173"

REM --- Billing Frontend ---
start "BizAssist Billing" powershell -ExecutionPolicy Bypass -NoExit -Command ^
  "cd '%ROOT%frontend-billing'; if (-not (Test-Path 'node_modules')) { npm install }; Write-Host 'Billing App → http://127.0.0.1:5174' -ForegroundColor Yellow; npm run dev -- --port 5174"

echo.
echo  Started:
echo   - Backend on :8001
echo   - AI Dashboard on :5173
echo   - Billing App on :5174
echo  Close the opened windows to stop.
echo.
