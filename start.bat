@echo off
REM ──────────────────────────────────────────────────
REM  Moodle Quiz Assistant — Quick Start Script
REM ──────────────────────────────────────────────────

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║   Gemini-Powered Moodle Quiz Assistant   ║
echo  ╚══════════════════════════════════════════╝
echo.

REM Check if .env exists
if not exist ".env" (
    echo [SETUP] Copying .env.example to .env...
    copy .env.example .env
    echo [ACTION] Open .env and set your GEMINI_API_KEY before running!
    pause
    exit /b 1
)

REM Check if venv exists
if not exist "venv" (
    echo [SETUP] Creating virtual environment...
    python -m venv venv
)

REM Activate venv
call venv\Scripts\activate.bat

REM Install dependencies
echo [SETUP] Installing dependencies...
pip install -r requirements.txt --quiet

REM Install Playwright browsers
echo [SETUP] Installing Playwright Chromium browser...
playwright install chromium

REM Free port 8000 if occupied by a previous session
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1


REM Run the app
echo.
echo [START] Starting server at http://127.0.0.1:8000
echo [INFO]  Press Ctrl+C to stop
echo.
python run.py

