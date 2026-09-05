@echo off
REM Build local_print_agent\python\ (embeddable 3.12 + pywin32) on this PC.
REM Requires internet. Run on the SmartWagers server / build machine before
REM serving Admin -> Print Agent downloads.
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: System Python not found. Need any Python on PATH to run prepare_vendor.py
    pause
    exit /b 1
)
python "%~dp0prepare_vendor.py"
set ERR=%ERRORLEVEL%
if not "%ERR%"=="0" (
    pause
    exit /b %ERR%
)
echo.
pause
exit /b 0
