@echo off
REM ============================================================
REM  SmartWagers — Apply an incremental release on the server.
REM
REM  Reads deploy\.last_sync_manifest (written by sync_release.py),
REM  runs migrate/collectstatic when needed, then restarts Daphne.
REM
REM  Usually invoked automatically over SSH by sync_release.py.
REM  Safe to run manually on the server after copying changed files.
REM ============================================================

setlocal EnableDelayedExpansion

cd /d "%~dp0.."
set PROJECT_DIR=%CD%
set MANIFEST=%PROJECT_DIR%\deploy\.last_sync_manifest
set NSSM=C:\SmartWagers\nssm\nssm.exe
set SERVICE=SmartWagers-Daphne
set LOG_DIR=C:\SmartWagers\logs
set PYTHON_PATH_FILE=%PROJECT_DIR%\deploy\python_path.txt

set PYTHON_EXE=python
if exist "%PYTHON_PATH_FILE%" set /p PYTHON_EXE=<"%PYTHON_PATH_FILE%"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo [%date% %time%] apply_release starting>> "%LOG_DIR%\deploy_apply.log"
echo PROJECT_DIR=%PROJECT_DIR%>> "%LOG_DIR%\deploy_apply.log"

set RUN_MIGRATE=0
set RUN_COLLECTSTATIC=0
set RUN_RESTART=0

if not exist "%MANIFEST%" (
    echo WARNING: manifest not found at %MANIFEST%
    echo WARNING: manifest not found at %MANIFEST%>> "%LOG_DIR%\deploy_apply.log"
    set RUN_MIGRATE=1
    set RUN_COLLECTSTATIC=1
    set RUN_RESTART=1
    goto :run_tasks
)

for /f "usebackq delims=" %%F in ("%MANIFEST%") do (
    set "REL=%%F"
    if /i "!REL!"=="" (
        rem skip blank lines
    ) else (
        echo manifest: !REL!>> "%LOG_DIR%\deploy_apply.log"
        echo !REL! | findstr /I /R "\\.py$ manage.py requirements.txt" >nul && set RUN_RESTART=1
        echo !REL! | findstr /I /R "SmartWagers/migrations/ SmartWagers\\migrations\\" >nul && set RUN_MIGRATE=1
        echo !REL! | findstr /I /R "SmartWagers/static/ SmartWagers/templates/ SmartWagers\\static\\ SmartWagers\\templates\\ .*\\.js .*\\.css" >nul && set RUN_COLLECTSTATIC=1
    )
)

if "%RUN_RESTART%"=="1" set RUN_MIGRATE=1

:run_tasks
if "%RUN_MIGRATE%"=="1" (
    echo Running database migrations...
    echo [%date% %time%] migrate>> "%LOG_DIR%\deploy_apply.log"
    "%PYTHON_EXE%" manage.py migrate
    if errorlevel 1 (
        echo ERROR: migrate failed.
        echo [%date% %time%] ERROR migrate failed>> "%LOG_DIR%\deploy_apply.log"
        exit /b 1
    )
) else (
    echo Skipping migrate ^(no migration files in manifest^).
)

if "%RUN_COLLECTSTATIC%"=="1" (
    echo Collecting static files...
    echo [%date% %time%] collectstatic>> "%LOG_DIR%\deploy_apply.log"
    "%PYTHON_EXE%" manage.py collectstatic --no-input
    if errorlevel 1 (
        echo ERROR: collectstatic failed.
        echo [%date% %time%] ERROR collectstatic failed>> "%LOG_DIR%\deploy_apply.log"
        exit /b 1
    )
) else (
    echo Skipping collectstatic ^(no static/template assets in manifest^).
)

if "%RUN_RESTART%"=="1" (
    if exist "%NSSM%" (
        echo Restarting %SERVICE%...
        echo [%date% %time%] restart %SERVICE%>> "%LOG_DIR%\deploy_apply.log"
        "%NSSM%" restart %SERVICE%
        if errorlevel 1 (
            echo ERROR: service restart failed.
            echo [%date% %time%] ERROR service restart failed>> "%LOG_DIR%\deploy_apply.log"
            exit /b 1
        )
    ) else (
        echo WARNING: NSSM not found at %NSSM%. Restart Daphne manually.
        echo [%date% %time%] WARNING nssm missing>> "%LOG_DIR%\deploy_apply.log"
    )
) else (
    echo Skipping service restart ^(manifest had no runtime code changes^).
)

echo.
echo Incremental release applied successfully.
echo Log: %LOG_DIR%\deploy_apply.log
echo [%date% %time%] apply_release complete>> "%LOG_DIR%\deploy_apply.log"
exit /b 0
