@echo off
REM ============================================================
REM  SmartWagers — Initialize master lock state (once)
REM  Creates C:\SmartWagers\data\master_lock.state as DISABLED.
REM  Does NOT overwrite an existing state file.
REM
REM  Prerequisites:
REM    - .env contains MASTER_LOCK_REQUIRED=True
REM    - MASTER_LOCK_SIGNING_KEY and MASTER_LOCK_PASSWORD_HASH set
REM    - Run from project root or this deploy folder
REM ============================================================

setlocal
set PROJECT_DIR=C:\SmartWagers\GameFowl
set DATA_DIR=C:\SmartWagers\data
set PYTHON_PATH_FILE=%PROJECT_DIR%\deploy\python_path.txt

if not exist "%DATA_DIR%" (
    echo Creating %DATA_DIR% ...
    mkdir "%DATA_DIR%"
)

set PYTHON_EXE=python
if exist "%PYTHON_PATH_FILE%" (
    set /p PYTHON_EXE=<"%PYTHON_PATH_FILE%"
)

cd /d "%PROJECT_DIR%"
echo Initializing master lock state...
"%PYTHON_EXE%" manage.py init_master_lock
if errorlevel 1 (
    echo.
    echo ERROR: init_master_lock failed.
    echo        Ensure MASTER_LOCK_SIGNING_KEY and MASTER_LOCK_PASSWORD_HASH
    echo        are set in .env, then re-run this script.
    pause
    exit /b 1
)

echo.
echo Done. Restrict ACLs on %DATA_DIR% to Administrators + the Daphne service account.
echo.
pause
endlocal
