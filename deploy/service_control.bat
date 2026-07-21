@echo off
REM ============================================================
REM  SmartWagers — Service control helper
REM  Usage: service_control.bat [start|stop|restart|status|logs]
REM  Run as Administrator for start/stop/restart.
REM ============================================================

set SERVICE=SmartWagers-Daphne
set NSSM=C:\SmartWagers\nssm\nssm.exe
set LOG_DIR=C:\SmartWagers\logs

if "%1"=="start"   goto :start
if "%1"=="stop"    goto :stop
if "%1"=="restart" goto :restart
if "%1"=="status"  goto :status
if "%1"=="logs"    goto :logs

echo Usage: %~nx0 [start^|stop^|restart^|status^|logs]
goto :end

:start
echo Starting %SERVICE% ...
REM A PAUSED service (NSSM throttle-delay after a crash) cannot accept
REM SC_CONTROL_START.  Detect the state and handle each case correctly.
for /f "tokens=*" %%s in ('%NSSM% status %SERVICE% 2^>nul') do set _SVC_STATE=%%s

if /i "%_SVC_STATE%"=="SERVICE_RUNNING" (
    echo Service is already RUNNING.
    goto :end
)
if /i "%_SVC_STATE%"=="SERVICE_PAUSED" (
    echo Service is stuck in PAUSED state ^(NSSM throttle delay after a crash^).
    echo Performing full stop-then-start to clear the throttle...
    sc continue %SERVICE% >nul 2>&1
    timeout /t 2 /nobreak >nul
    %NSSM% stop %SERVICE% >nul 2>&1
    timeout /t 3 /nobreak >nul
)
%NSSM% start %SERVICE%
goto :end

:stop
echo Stopping %SERVICE% ...
%NSSM% stop %SERVICE%
goto :end

:restart
echo Restarting %SERVICE% ...
%NSSM% restart %SERVICE%
goto :end

:status
echo Status of %SERVICE%:
%NSSM% status %SERVICE%
goto :end

:logs
echo Opening log files...
start notepad "%LOG_DIR%\daphne_stdout.log"
start notepad "%LOG_DIR%\daphne_stderr.log"
goto :end

:end
pause
