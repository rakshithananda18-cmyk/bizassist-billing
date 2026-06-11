@echo off
REM Double-click to run backend + frontend tests.
REM Pass an argument to limit:  run_tests.bat backend   |   run_tests.bat frontend
powershell -ExecutionPolicy Bypass -File "%~dp0run_tests.ps1" %1
echo.
pause
