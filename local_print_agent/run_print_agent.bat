@echo off
REM Starts the print agent in the background (no console window).
REM For a visible debug console, run:  python\python.exe print_agent.py
cd /d "%~dp0"
if exist "%~dp0start_print_agent_silent.vbs" (
    wscript //nologo "%~dp0start_print_agent_silent.vbs"
    exit /b %ERRORLEVEL%
)
if exist "%~dp0python\pythonw.exe" (
    start "" /D "%~dp0" "%~dp0python\pythonw.exe" print_agent.py
    exit /b 0
)
if exist "%~dp0python\python.exe" (
    start "" /D "%~dp0" /min "%~dp0python\python.exe" print_agent.py
    exit /b 0
)
where pythonw >nul 2>&1
if not errorlevel 1 (
    start "" /D "%~dp0" pythonw print_agent.py
    exit /b 0
)
start "" /D "%~dp0" /min python print_agent.py
