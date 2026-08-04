@echo off
setlocal
cd /d "%~dp0.."

if "%~1"=="" (
    echo Usage: deploy\8_restore_postgres.bat C:\path\to\backup.dump
    echo.
    echo WARNING: Restore replaces the current smartwagers database contents.
    pause
    exit /b 1
)

set /p CONFIRM=Type the PostgreSQL database name to confirm destructive restore: 
python deploy\postgres_tools.py restore "%~1" --confirm-database "%CONFIRM%"
if errorlevel 1 (
    echo.
    echo ERROR: PostgreSQL restore failed.
    pause
    exit /b 1
)

echo.
echo Restore complete. Run python manage.py check_database and the verification command.
pause
endlocal
