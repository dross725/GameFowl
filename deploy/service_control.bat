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
