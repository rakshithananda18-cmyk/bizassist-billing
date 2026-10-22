@echo off
REM Double-click to run backend + frontend tests (same as bizassist-billing).
REM
REM Limit which suite:
REM     run_tests.bat backend        (backend only)
REM     run_tests.bat frontend       (frontend only)
REM
REM Go parallel (faster backend, uses pytest-xdist from requirements-dev.txt):
REM     run_tests.bat fast           (both suites, backend parallel)
REM     run_tests.bat backend fast   (backend only, parallel)

set "SCOPE=%~1"
set "SPEED=%~2"

REM Allow "run_tests.bat fast" as a shorthand for all-suites-parallel.
if /I "%SCOPE%"=="fast" (
    set "SCOPE=all"
    set "SPEED=fast"
)
if "%SCOPE%"=="" set "SCOPE=all"

set "FASTFLAG="
if /I "%SPEED%"=="fast" set "FASTFLAG=-Fast"

powershell -ExecutionPolicy Bypass -File "%~dp0run_tests.ps1" %SCOPE% %FASTFLAG%
echo.
pause
