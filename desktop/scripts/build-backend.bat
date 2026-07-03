@echo off
REM ============================================================
REM build-backend.bat — compile FastAPI backend with PyInstaller
REM and stage it into desktop\resources\backend  (Windows)
REM ============================================================
setlocal
set ROOT=%~dp0..\..
set BACKEND=%ROOT%\backend
set DEST=%~dp0..\resources\backend

echo [1/4] Ensuring venv + deps...
if not exist "%ROOT%\venv\Scripts\python.exe" (
    python -m venv "%ROOT%\venv" || exit /b 1
)
call "%ROOT%\venv\Scripts\activate.bat"
python -m pip install --upgrade pip >nul
pip install -r "%ROOT%\requirements.txt" pyinstaller || exit /b 1

echo [2/4] Running PyInstaller (this takes a while)...
cd /d "%BACKEND%"
pyinstaller bizassist-backend.spec --noconfirm || exit /b 1

echo [3/4] Staging into desktop\resources\backend...
if exist "%DEST%" rmdir /s /q "%DEST%"
xcopy /e /i /y "%BACKEND%\dist\bizassist-backend" "%DEST%" >nul || exit /b 1

echo [4/4] Smoke test (health check)...
start /b "" "%DEST%\bizassist-backend.exe" --port 8009
timeout /t 15 /nobreak >nul
curl -sf http://127.0.0.1:8009/health && echo OK || echo WARNING: health check failed - inspect manually
taskkill /im bizassist-backend.exe /f >nul 2>&1

echo Done. Backend staged at %DEST%
endlocal
