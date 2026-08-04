@echo off
setlocal
cd /d "%~dp0.."

echo ============================================================
echo  SmartWagers users-only SQLite to PostgreSQL migration
echo ============================================================
echo.
echo This copies ONLY auth users and groups ^(admin/teller/display^).
echo Wagers, payouts, events, totals, and fight status are NOT copied.
echo.
echo IMPORTANT: Point this at the OLD db.sqlite3 that still contains
echo your login accounts. A fresh GameFowl copy usually has no users.
echo.
echo Prerequisites:
echo   1. Daphne is stopped
echo   2. PostgreSQL is running and .env POSTGRES_* values are correct
echo   3. You know the full path to the old SQLite file
echo.
set /p SQLITE_PATH=Full path to OLD db.sqlite3: 
if "%SQLITE_PATH%"=="" (
    echo ERROR: SQLite path is required.
    pause
    exit /b 1
)
if not exist "%SQLITE_PATH%" (
    echo ERROR: File not found: %SQLITE_PATH%
    pause
    exit /b 1
)

set /p CONFIRM=Type USERS to continue: 
if /I not "%CONFIRM%"=="USERS" (
    echo Migration cancelled.
    exit /b 1
)

echo Stopping SmartWagers-Daphne...
sc stop SmartWagers-Daphne >nul 2>&1
ping -n 4 127.0.0.1 >nul

python deploy\migrate_users_to_postgres.py --confirm-downtime --sqlite "%SQLITE_PATH%"
if errorlevel 1 (
    echo.
    echo ERROR: Users-only migration failed. Daphne remains stopped.
    echo Review the workspace under C:\SmartWagers\backups.
    pause
    exit /b 1
)

echo.
echo Users and groups imported.
echo Next:
echo   1. python manage.py check_database
echo   2. deploy\service_control.bat start
echo   3. Log in with an old username/password
echo.
pause
endlocal
