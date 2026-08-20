@echo off
setlocal

set PROJECT_DIR=C:\SmartWagers\GameFowl
set OUTPUT=%~dp0server_inventory.json
set PYTHON_EXE=python

if exist "%PROJECT_DIR%\deploy\python_path.txt" (
    set /p PYTHON_EXE=<"%PROJECT_DIR%\deploy\python_path.txt"
)

echo Reading production files from %PROJECT_DIR%
echo Inventory will be written beside this script on the USB drive.
echo.

"%PYTHON_EXE%" "%~dp0release_inventory.py" snapshot --root "%PROJECT_DIR%" --output "%OUTPUT%"
if errorlevel 1 (
    echo.
    echo ERROR: Production inventory could not be created.
    pause
    exit /b 1
)

echo.
echo Created %OUTPUT%
echo Return this USB drive to the development PC for comparison.
pause
exit /b 0
