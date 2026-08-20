@echo off
setlocal
cd /d "%~dp0.."

set PROJECT_DIR=%CD%
set OUTPUT=%~1
if "%OUTPUT%"=="" set OUTPUT=C:\SmartWagers\server_inventory.json

set PYTHON_EXE=python
if exist "%PROJECT_DIR%\deploy\python_path.txt" (
    set /p PYTHON_EXE=<"%PROJECT_DIR%\deploy\python_path.txt"
)

echo Creating production file inventory...
echo Project: %PROJECT_DIR%
echo Output:  %OUTPUT%
echo.

"%PYTHON_EXE%" deploy\release_inventory.py snapshot --root "%PROJECT_DIR%" --output "%OUTPUT%"
if errorlevel 1 (
    echo.
    echo ERROR: Production inventory could not be created.
    pause
    exit /b 1
)

echo.
echo Inventory created successfully.
echo Copy %OUTPUT% to the development PC and use it with:
echo deploy\11_sync_release.bat --inventory INVENTORY.json --usb E:\SmartWagersReleases
pause
exit /b 0
