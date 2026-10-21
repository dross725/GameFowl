@echo off
REM Create the daily backup and commission-email retry tasks.
REM Pass "nopause" when called from another installer.
setlocal
set PROJECT_DIR=C:\SmartWagers\GameFowl
set PYTHON_EXE=python
if exist "%PROJECT_DIR%\deploy\python_path.txt" set /p PYTHON_EXE=<"%PROJECT_DIR%\deploy\python_path.txt"

schtasks /Create /F /TN "SmartWagers-PostgresBackup" /SC DAILY /ST 02:00 /RL LIMITED /TR "\"%PYTHON_EXE%\" \"%PROJECT_DIR%\deploy\postgres_tools.py\" backup-maintain"
if errorlevel 1 (
    echo ERROR: Could not schedule the PostgreSQL backup.
    if /I not "%~1"=="nopause" pause
    exit /b 1
)

schtasks /Create /F /TN "SmartWagers-SendPendingReports" /SC MINUTE /MO 5 /RL LIMITED /TR "\"%PYTHON_EXE%\" \"%PROJECT_DIR%\manage.py\" send_pending_event_reports"
if errorlevel 1 (
    echo ERROR: Could not schedule commission email retry.
    if /I not "%~1"=="nopause" pause
    exit /b 1
)

echo Scheduled SmartWagers-PostgresBackup daily at 02:00.
echo Scheduled SmartWagers-SendPendingReports every 5 minutes.
echo Backups are validated and 14 dumps are retained.
if /I not "%~1"=="nopause" pause
exit /b 0
