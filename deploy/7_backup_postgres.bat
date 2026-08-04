@echo off
setlocal
cd /d "%~dp0.."

echo Creating PostgreSQL backup...
python deploy\postgres_tools.py backup
if errorlevel 1 (
    echo.
    echo ERROR: PostgreSQL backup failed.
    echo Check .env credentials and ensure PostgreSQL bin is on PATH.
    pause
    exit /b 1
)

echo.
echo Backup complete. Files are stored under C:\SmartWagers\backups.
pause
endlocal
