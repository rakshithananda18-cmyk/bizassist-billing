@echo off
setlocal

echo ==================================
echo  BIZASSIST — STARTING BACKEND
echo ==================================
echo.

REM Check venv exists
if not exist "venv\Scripts\activate" (
    echo ERROR: Virtual environment not found.
    echo Run dependencies.bat first to set up the project.
    pause
    exit /b 1
)

REM Check .env exists
if not exist "backend\.env" (
    echo ERROR: backend\.env not found.
    echo Copy .env.example to backend\.env and add your GROQ_API_KEY.
    pause
    exit /b 1
)

echo Activating virtual environment...
call venv\Scripts\activate

echo Starting BizAssist backend on http://localhost:8001
echo.
echo Press Ctrl+C to stop the server.
echo.

cd backend
python -m uvicorn main_groq:app --reload --port 8001
