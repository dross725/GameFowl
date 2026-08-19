@echo off
REM Visible console for troubleshooting teller print agent startup.
cd /d "%~dp0"
echo SmartWagers print agent debug launcher
echo Folder: %CD%
echo.
python --version 2>nul
if errorlevel 1 (
    echo ERROR: python not found in PATH.
    echo Install Python from https://python.org and check "Add to PATH".
    pause
    exit /b 1
)
echo.
python -m py_compile print_agent.py
if errorlevel 1 (
    echo ERROR: print_agent.py has a syntax error.
    pause
    exit /b 1
)
echo Starting agent... open http://127.0.0.1:8765/health in a browser.
echo Press Ctrl+C to stop.
echo.
python print_agent.py
echo.
echo Agent exited with code %ERRORLEVEL%
pause
