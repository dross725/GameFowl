@echo off
REM ============================================================
REM  SmartWagers — Incremental deploy helper (Windows dev PC)
REM
REM  Uses git to find changed files and copies them to the
REM  production project folder, then runs 11_apply_release.bat.
REM
REM  Typical server path: C:\SmartWagers\GameFowl
REM  Edit deploy\sync_config.env and set:
REM    DEPLOY_METHOD=copy
REM    DEPLOY_LOCAL_ROOT=C:\SmartWagers\GameFowl
REM ============================================================

cd /d "%~dp0.."

if not exist "deploy\sync_config.env" (
    echo Copy deploy\sync_config.example.env to deploy\sync_config.env first.
    pause
    exit /b 1
)

python deploy/sync_release.py %*
if errorlevel 1 (
    pause
    exit /b 1
)

echo.
pause
