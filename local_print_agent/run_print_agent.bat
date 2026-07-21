@echo off
REM Starts the print agent in the background (no console window).
REM For a visible debug console, run:  python print_agent.py
cd /d "%~dp0"
if exist "%~dp0start_print_agent_silent.vbs" (
    wscript //nologo "%~dp0start_print_agent_silent.vbs"
    exit /b %ERRORLEVEL%
)
where pythonw >nul 2>&1
if not errorlevel 1 (
    start "" /D "%~dp0" pythonw print_agent.py
    exit /b 0
)
start "" /D "%~dp0" /min python print_agent.py
