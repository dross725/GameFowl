@echo off
setlocal
cd /d "%~dp0.."

echo ============================================================
echo  SmartWagers SQLite to PostgreSQL migration
echo ============================================================
echo.
echo This requires a planned maintenance window.
echo All teller, admin, and display browsers must stop using the app.
echo The PostgreSQL target must contain no SmartWagers data.
echo.
set /p CONFIRM=Type MIGRATE to stop Daphne and continue: 
if /I not "%CONFIRM%"=="MIGRATE" (
    echo Migration cancelled.
    exit /b 1
)

echo Stopping SmartWagers-Daphne...
sc stop SmartWagers-Daphne >nul 2>&1
ping -n 4 127.0.0.1 >nul

python deploy\migrate_sqlite_to_postgres.py --confirm-downtime
if errorlevel 1 (
    echo.
    echo ERROR: Migration failed. Daphne remains stopped.
    echo Review the migration workspace under C:\SmartWagers\backups.
    echo Restore the frozen SQLite .env/database if rollback is required.
    pause
    exit /b 1
)

echo.
echo Migration and data comparison succeeded.
echo Run the smoke-test checklist before starting Daphne:
echo   deploy\service_control.bat start
echo.
pause
endlocal
