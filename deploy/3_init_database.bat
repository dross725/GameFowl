@echo off
REM ============================================================
REM  SmartWagers — Step 3: Initialize the database and collect
REM  static files.
REM  Run from the project root: C:\SmartWagers\GameFowl\
REM  Run ONCE on first deploy. Safe to re-run (migrate is
REM  idempotent; collectstatic will overwrite, that is fine).
REM ============================================================

cd /d "%~dp0.."

echo Running database migrations...
python manage.py migrate
if errorlevel 1 (
    echo ERROR: migrate failed. Check .env exists and is correct.
    pause
    exit /b 1
)

echo.
echo Collecting static files...
python manage.py collectstatic --no-input
if errorlevel 1 (
    echo ERROR: collectstatic failed.
    pause
    exit /b 1
)

echo.
echo Database and static files ready.
echo.
echo Next: create the Django superuser account.
echo       python manage.py createsuperuser
echo.
echo After that, log in to http://localhost:8000/admin/ and:
echo   1. Create three Groups: admin, teller, display
echo   2. Create user accounts and assign each to its group.
echo.
pause
