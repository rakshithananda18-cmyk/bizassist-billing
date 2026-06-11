@echo off
REM Double-click to start backend + frontend dev servers (each in its own window).
REM For DEBUG backend logs:  start_dev.bat debug
if /I "%1"=="debug" (
    powershell -ExecutionPolicy Bypass -File "%~dp0start_dev.ps1" -Dbg
) else (
    powershell -ExecutionPolicy Bypass -File "%~dp0start_dev.ps1"
)
