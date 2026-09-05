@echo off
REM Visible console for troubleshooting teller print agent startup.
cd /d "%~dp0"
setlocal
set PY=
if exist "%~dp0python\python.exe" (
    set "PY=%~dp0python\python.exe"
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Bundled python\python.exe not found and python is not on PATH.
        echo Re-download the Print Agent package from Admin -^> Print Agent.
        pause
        exit /b 1
    )
    set "PY=python"
)
echo SmartWagers print agent debug launcher
echo Folder: %CD%
echo Python: %PY%
echo.
"%PY%" --version
if errorlevel 1 (
    echo ERROR: could not run Python.
    pause
    exit /b 1
)
echo.
"%PY%" -m py_compile print_agent.py
if errorlevel 1 (
    echo ERROR: print_agent.py has a syntax error.
    pause
    exit /b 1
)
echo Starting agent... open http://127.0.0.1:8765/health in a browser.
echo Press Ctrl+C to stop.
echo.
"%PY%" print_agent.py
echo.
echo Agent exited with code %ERRORLEVEL%
pause
endlocal
