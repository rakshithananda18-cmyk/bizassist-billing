@echo off
setlocal

echo ==================================
echo  BIZASSIST - SETUP
echo ==================================
echo.

REM Check Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found.
    pause
    exit /b 1
)

REM Check Node.js is installed
node --version >nul 2>&1
if errorlevel 1 (
    echo WARNING: Node.js not found.
)

REM Check npm is installed
call npm --version >nul 2>&1
if errorlevel 1 (
    echo WARNING: npm not found.
)

echo.
echo [1/5] Checking virtual environment...

if exist "venv\Scripts\python.exe" (
    echo      venv already exists - reusing it.
) else (
    echo      Creating virtual environment...
    python -m venv venv

    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
)

echo.
echo [2/5] Activating virtual environment...

call venv\Scripts\activate.bat

echo.
echo [3/5] Upgrading pip...

venv\Scripts\python.exe -m pip install --upgrade pip

echo.
echo [4/5] Installing Python dependencies...

if exist "requirements.txt" (
    venv\Scripts\python.exe -m pip install --prefer-binary -r requirements.txt
)

echo.
echo [5/5] Installing frontend dependencies...

if exist "frontend-ai\package.json" (
    pushd frontend-ai
    call npm install
    popd
)

if exist "frontend-billing\package.json" (
    pushd frontend-billing
    call npm install
    popd
)

echo.
echo ==================================
echo  SETUP COMPLETE
echo ==================================

pause