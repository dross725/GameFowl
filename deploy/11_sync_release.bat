@echo off
REM ============================================================
REM  SmartWagers — Incremental deploy helper (Windows dev PC)
REM
REM  Uses git to find changed files. It can either sync over the
REM  network or create a self-contained package on a USB drive.
REM
REM  Offline USB example:
REM    deploy\11_sync_release.bat --usb E:\SmartWagersReleases
REM
REM  Network/copy modes use deploy\sync_config.env.
REM ============================================================

cd /d "%~dp0.."

python deploy/sync_release.py %*
if errorlevel 1 (
    pause
    exit /b 1
)

echo.
pause
