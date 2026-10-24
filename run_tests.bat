@echo off
REM Run tests for Moodle Quiz Assistant
echo Running tests...
call venv\Scripts\activate.bat 2>nul || python -m venv venv && call venv\Scripts\activate.bat && pip install -r requirements.txt -q
python -m pytest tests\ -v --tb=short
pause
