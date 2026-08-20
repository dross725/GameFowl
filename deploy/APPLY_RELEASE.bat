@echo off
setlocal
cd /d "%~dp0"

echo SmartWagers Offline USB Release
echo Package: %CD%
echo.

set PYTHON_EXE=python
if exist "C:\SmartWagers\GameFowl\deploy\python_path.txt" (
    set /p PYTHON_EXE=<"C:\SmartWagers\GameFowl\deploy\python_path.txt"
)

"%PYTHON_EXE%" "%~dp0apply_usb_release.py" %*
set EXITCODE=%ERRORLEVEL%
if not "%EXITCODE%"=="0" (
    echo.
    echo ERROR: Release was not applied successfully.
    echo Review C:\SmartWagers\logs\usb_release.log for details.
    pause
    exit /b %EXITCODE%
)

echo.
echo Release applied successfully. The USB drive may now be removed.
pause
exit /b 0
