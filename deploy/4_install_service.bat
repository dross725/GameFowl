@echo off
REM ============================================================
REM  SmartWagers — Step 4: Register Daphne as a Windows service
REM  using NSSM (Non-Sucking Service Manager).
REM
REM  PREREQUISITES:
REM    - Run this script as Administrator
REM    - NSSM extracted to C:\SmartWagers\nssm\nssm.exe
REM      Download from: https://nssm.cc/download
REM    - .env file created (run 1_setup_env.bat first)
REM    - Dependencies installed (run 2_install_deps.bat first)
REM
REM  Run from anywhere — paths are resolved automatically.
REM ============================================================

set NSSM=C:\SmartWagers\nssm\nssm.exe
set SERVICE=SmartWagers-Daphne
set PROJECT_DIR=C:\SmartWagers\GameFowl
set LOG_DIR=C:\SmartWagers\logs

REM -- Resolve daphne.exe path
for /f "delims=" %%i in ('where daphne 2^>nul') do set DAPHNE_PATH=%%i
if "%DAPHNE_PATH%"=="" (
    echo ERROR: daphne.exe not found on PATH.
    echo        Run 2_install_deps.bat first, then retry.
    pause
    exit /b 1
)

if not exist "%NSSM%" (
    echo ERROR: NSSM not found at %NSSM%
    echo        Download nssm.exe from https://nssm.cc/download
    echo        and extract it to C:\SmartWagers\nssm\
    pause
    exit /b 1
)

REM -- Read the .env file to extract settings for the service environment
set ENV_FILE=%PROJECT_DIR%\.env
if not exist "%ENV_FILE%" (
    echo ERROR: .env not found at %ENV_FILE%
    echo        Run 1_setup_env.bat first.
    pause
    exit /b 1
)

echo Creating log directory at %LOG_DIR% ...
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo.
echo Removing old service if it exists...
%NSSM% stop %SERVICE% 2>nul
%NSSM% remove %SERVICE% confirm 2>nul

echo.
echo Installing %SERVICE% ...
%NSSM% install %SERVICE% "%DAPHNE_PATH%" -b 0.0.0.0 -p 8000 GameFowl.asgi:application

REM -- Service settings
%NSSM% set %SERVICE% AppDirectory        "%PROJECT_DIR%"
%NSSM% set %SERVICE% DisplayName         "SmartWagers Daphne ASGI Server"
%NSSM% set %SERVICE% Description         "SmartWagers sabong wagering system - Daphne ASGI"
%NSSM% set %SERVICE% Start               SERVICE_AUTO_START
%NSSM% set %SERVICE% AppStdout           "%LOG_DIR%\daphne_stdout.log"
%NSSM% set %SERVICE% AppStderr           "%LOG_DIR%\daphne_stderr.log"
%NSSM% set %SERVICE% AppRotateFiles      1
%NSSM% set %SERVICE% AppRotateBytes      10485760

REM -- Set only DJANGO_SETTINGS_MODULE on the service.
REM    All other variables (SECRET_KEY, DEBUG, ALLOWED_HOSTS, etc.) are read
REM    from the .env file automatically by settings.py at startup, so they
REM    do not need to be injected here.
%NSSM% set %SERVICE% AppEnvironmentExtra "DJANGO_SETTINGS_MODULE=GameFowl.settings"

echo.
echo Starting service...
%NSSM% start %SERVICE%
if errorlevel 1 (
    echo WARNING: Service may not have started. Check logs at %LOG_DIR%
) else (
    echo Service started successfully.
)

echo.
echo Verify: open http://localhost:8000/login in a browser.
echo Logs:   %LOG_DIR%\daphne_stdout.log
echo         %LOG_DIR%\daphne_stderr.log
echo.
pause
