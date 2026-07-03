@echo off
REM ============================================================
REM build-all.bat — one-shot local build of the Windows installer
REM   frontends → renderer staging → backend (PyInstaller) → NSIS
REM Output: desktop\release\BizAssist-Setup-<version>.exe
REM ============================================================
setlocal
set ROOT=%~dp0..\..

echo === [1/5] Building frontend-billing ===
cd /d "%ROOT%\frontend-billing"
call npm ci || exit /b 1
call npm run build || exit /b 1

echo === [2/5] Building frontend-ai ===
cd /d "%ROOT%\frontend-ai"
call npm ci || exit /b 1
call npm run build || exit /b 1

echo === [3/5] Staging renderers ===
cd /d "%ROOT%\desktop"
call npm ci || exit /b 1
call node scripts\prepare-renderer.js || exit /b 1

echo === [4/5] Building backend (PyInstaller) ===
call scripts\build-backend.bat || exit /b 1

echo === [5/5] Packaging installer (electron-builder) ===
cd /d "%ROOT%\desktop"
call npx electron-builder --win --publish never || exit /b 1

echo.
echo Installer ready in desktop\release\
endlocal
