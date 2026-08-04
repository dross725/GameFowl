@echo off
REM ============================================================
REM  SmartWagers — Step 1: Create the production .env file
REM  Run this ONCE from: C:\SmartWagers\GameFowl\deploy\
REM  Edit the IP address before running.
REM
REM  Secrets are written by Python (not CMD echo) so characters like
REM  !, *, ), & in secret keys do not break the batch parser.
REM ============================================================

setlocal

REM ---- EDIT THIS LINE with the actual IP of this server ----
set SERVER_IP=192.168.1.10
REM ----------------------------------------------------------

set "ENV_FILE=%~dp0..\.env"

if exist "%ENV_FILE%" (
    echo .env already exists. Delete it manually if you want to regenerate.
    pause
    exit /b 1
)

echo Generating .env file with Python...
python "%~dp0write_env.py" "%ENV_FILE%" "%SERVER_IP%"
if errorlevel 1 (
    echo.
    echo ERROR: Could not generate .env. Is Python installed and on PATH?
    pause
    exit /b 1
)

echo.
echo .env created at %ENV_FILE%
echo.
echo IMPORTANT:
echo   1. Open .env and verify SERVER_IP is correct: %SERVER_IP%
echo   2. Install PostgreSQL and create the database/user using the generated
echo      POSTGRES_DB, POSTGRES_USER, and POSTGRES_PASSWORD values in .env.
echo   3. After installing deps ^(2_install_deps.bat^), generate the master key hash:
echo        python manage.py hash_master_lock_key
echo      then paste the output into MASTER_LOCK_PASSWORD_HASH=
echo   4. Run deploy\6_init_master_lock.bat to create the disabled state file
echo.
pause
endlocal
