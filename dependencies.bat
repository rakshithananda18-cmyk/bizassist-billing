@echo off
setlocal

echo ==================================
echo  BIZASSIST — SETUP
echo ==================================
echo.

REM Check Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

echo [1/4] Creating virtual environment...
python -m venv venv
if %errorlevel% neq 0 (
    echo ERROR: Failed to create venv.
    pause
    exit /b 1
)

echo [2/4] Activating virtual environment...
call venv\Scripts\activate

echo [3/4] Upgrading pip...
python -m pip install --upgrade pip --quiet

echo [4/4] Installing dependencies...
pip install --prefer-binary -r requirements.txt
if %errorlevel% neq 0 (
    echo ERROR: pip install failed. Check requirements.txt and your internet connection.
    pause
    exit /b 1
)

echo.
echo ==================================
echo  SETUP COMPLETE
echo ==================================
echo.
echo Next steps:
echo  1. Copy .env.example to .env and fill in your keys:
echo       - GROQ_API_KEY (required for AI)
echo       - EMAIL_USER / EMAIL_PASS (for email alerts)
echo       - TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN (for WhatsApp alerts)
echo  2. Run start.bat to launch the backend
echo  3. Open frontend\index.html with VS Code Live Server (port 5500)
echo  4. Configure alerts via: POST /alerts/config
echo  5. Test alerts via:      POST /alerts/test/daily_summary
echo.
pause
