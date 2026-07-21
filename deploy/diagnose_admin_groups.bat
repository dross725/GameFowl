@echo off
REM ============================================================
REM  Diagnose Django admin Groups 500 errors
REM  Run from an Admin Command Prompt on the server.
REM ============================================================

cd /d C:\SmartWagers\GameFowl

echo.
echo === Reproduce tip ===
echo Click Groups in Django admin to trigger the 500, then continue.
pause

echo.
echo === Tail of GameFowl logs\app.log ===
if exist logs\app.log (
    powershell -NoProfile -Command "Get-Content 'logs\app.log' -Tail 80"
) else (
    echo logs\app.log not found
)

echo.
echo === Tail of NSSM daphne_stderr.log ===
if exist C:\SmartWagers\logs\daphne_stderr.log (
    powershell -NoProfile -Command "Get-Content 'C:\SmartWagers\logs\daphne_stderr.log' -Tail 80"
) else (
    echo C:\SmartWagers\logs\daphne_stderr.log not found
)

echo.
echo === Permission / content-type check ===
python deploy\check_admin_groups.py

echo.
echo Paste the traceback section above back into chat.
pause
