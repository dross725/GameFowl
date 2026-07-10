@echo off
REM ============================================================
REM  SmartWagers — Install the local print agent on this PC
REM  Run this on each Windows cashier/teller PC.
REM
REM  What it does:
REM    1. Installs pywin32 (Windows printer driver support)
REM    2. Creates config.json from the example if not present
REM    3. Adds run_print_agent.bat to Windows Startup so the
REM       agent launches automatically when the user logs in
REM ============================================================

REM -- Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found.
    echo        Install Python from https://python.org ^(check "Add to PATH"^)
    pause
    exit /b 1
)

echo Installing pywin32 for Windows printer support...
python -m pip install pywin32
if errorlevel 1 (
    echo ERROR: Failed to install pywin32.
    pause
    exit /b 1
)

REM -- Create config.json if it does not already exist
set AGENT_DIR=%~dp0
if not exist "%AGENT_DIR%config.json" (
    echo Creating config.json from template...
    copy "%AGENT_DIR%config.example.json" "%AGENT_DIR%config.json"
    echo.
    echo ACTION REQUIRED: Open config.json and set "printer_name" to the
    echo exact Windows printer queue name for this PC's receipt printer.
    echo Leave it empty ^("printer_name": ""^) to use the Windows default printer.
    echo.
    start notepad "%AGENT_DIR%config.json"
    pause
) else (
    echo config.json already exists — skipping copy.
)

REM -- Add to Windows Startup folder so it runs on every login
set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set SHORTCUT=%STARTUP%\SmartWagers-PrintAgent.bat

echo.
echo Adding print agent to Windows Startup folder...
(
echo @echo off
echo cd /d "%AGENT_DIR%"
echo python print_agent.py
) > "%SHORTCUT%"

echo.
echo Done. The print agent will start automatically on next login.
echo.
echo To start it now, run:
echo   %AGENT_DIR%run_print_agent.bat
echo.
echo To test: open http://127.0.0.1:8765/health in a browser on this PC.
echo.
pause
