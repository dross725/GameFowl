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
REM  The service runs deploy\run_daphne.bat via cmd.exe so startup
REM  failures are always written to C:\SmartWagers\logs\daphne_wrapper.log
REM ============================================================

set NSSM=C:\SmartWagers\nssm\nssm.exe
set SERVICE=SmartWagers-Daphne
set PROJECT_DIR=C:\SmartWagers\GameFowl
set LOG_DIR=C:\SmartWagers\logs
set RUNNER=%PROJECT_DIR%\deploy\run_daphne.bat
set CMD_EXE=%SystemRoot%\System32\cmd.exe

if not exist "%NSSM%" (
    echo ERROR: NSSM not found at %NSSM%
    echo        Download nssm.exe from https://nssm.cc/download
    echo        and extract it to C:\SmartWagers\nssm\
    pause
    exit /b 1
)

if not exist "%RUNNER%" (
    echo ERROR: Launcher not found at %RUNNER%
    echo        Make sure deploy\run_daphne.bat is on the server.
    pause
    exit /b 1
)

set ENV_FILE=%PROJECT_DIR%\.env
if not exist "%ENV_FILE%" (
    echo ERROR: .env not found at %ENV_FILE%
    echo        Run 1_setup_env.bat first.
    pause
    exit /b 1
)

REM -- Resolve the REAL python.exe (not the Windows Store stub).
REM    `where python` often returns:
REM      C:\Users\...\AppData\Local\Microsoft\WindowsApps\python.exe
REM    That stub works in an interactive shell but FAILS under a Windows
REM    service with exit code 9020.  Ask Python itself for sys.executable.
set PYTHON_PATH=
for /f "delims=" %%i in ('python -c "import sys; print(sys.executable)" 2^>nul') do set PYTHON_PATH=%%i

REM Fallback: Python launcher (py.exe), usually in C:\Windows
if "%PYTHON_PATH%"=="" (
    for /f "delims=" %%i in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set PYTHON_PATH=%%i
)

if "%PYTHON_PATH%"=="" (
    echo ERROR: Could not resolve python.exe path.
    echo        Open Command Prompt and run:
    echo          python -c "import sys; print(sys.executable)"
    echo        Then put that full path into deploy\python_path.txt and retry.
    pause
    exit /b 1
)

REM Reject the Microsoft Store alias — services cannot execute it.
echo %PYTHON_PATH% | find /I "WindowsApps" >nul
if not errorlevel 1 (
    echo.
    echo ERROR: Resolved Python path is the Windows Store stub:
    echo          %PYTHON_PATH%
    echo.
    echo        That path works in your user CMD but NOT as a Windows service.
    echo        Install Python from https://python.org and check
    echo        "Add python.exe to PATH" + "Install for all users".
    echo.
    echo        Or run this and copy the real path into deploy\python_path.txt:
    echo          py -3 -c "import sys; print(sys.executable)"
    echo.
    pause
    exit /b 1
)

if not exist "%PYTHON_PATH%" (
    echo ERROR: Python path does not exist: %PYTHON_PATH%
    pause
    exit /b 1
)

echo Using Python: %PYTHON_PATH%

REM Persist absolute python.exe path for the service launcher.
REM Windows services do not inherit the interactive user's PATH, so the
REM launcher must call python.exe by full path.
echo %PYTHON_PATH%> "%PROJECT_DIR%\deploy\python_path.txt"
echo Wrote python path to deploy\python_path.txt

for %%P in ("%PYTHON_PATH%") do set PYTHON_DIR=%%~dpP
set PYTHON_DIR=%PYTHON_DIR:~0,-1%
echo Python directory: %PYTHON_DIR%

REM -- Pre-flight: Memurai
echo.
echo Checking Memurai connectivity...
memurai-cli ping >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: Memurai did not respond to PING.
    echo        Start Memurai from Services - services.msc - then start Memurai.
    echo        Verify with: memurai-cli ping
    pause
    exit /b 1
)
echo Memurai OK.

REM -- Pre-flight: Django
echo.
echo Verifying Django project...
cd /d "%PROJECT_DIR%"
"%PYTHON_PATH%" manage.py check
if errorlevel 1 (
    echo.
    echo ERROR: Django project failed to load. Fix the error above, then re-run.
    echo        If packages are missing, run 2_install_deps.bat with THIS Python.
    pause
    exit /b 1
)
echo Django OK.

REM -- Pre-flight: daphne module importable by THIS python
echo.
echo Verifying daphne module...
"%PYTHON_PATH%" -c "import daphne; print(daphne.__file__)"
if errorlevel 1 (
    echo.
    echo ERROR: daphne is not installed for this Python:
    echo          %PYTHON_PATH%
    echo        Run 2_install_deps.bat, then retry.
    pause
    exit /b 1
)

REM -- Pre-flight: ASGI app importable
echo.
echo Verifying ASGI application import...
set DJANGO_SETTINGS_MODULE=GameFowl.settings
"%PYTHON_PATH%" -c "import GameFowl.asgi; print('ASGI OK')"
if errorlevel 1 (
    echo.
    echo ERROR: GameFowl.asgi failed to import. Fix the error above, then re-run.
    pause
    exit /b 1
)

echo Creating log directory at %LOG_DIR% ...
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
type nul >> "%LOG_DIR%\daphne_stdout.log"
type nul >> "%LOG_DIR%\daphne_stderr.log"
type nul >> "%LOG_DIR%\daphne_wrapper.log"

echo.
echo Removing old service if it exists...
sc continue %SERVICE% >nul 2>&1
timeout /t 2 /nobreak >nul
%NSSM% stop %SERVICE% >nul 2>&1
timeout /t 3 /nobreak >nul
%NSSM% remove %SERVICE% confirm >nul 2>&1
timeout /t 2 /nobreak >nul

echo.
echo Installing %SERVICE% ...
REM Run via cmd.exe /c so .bat logging always works under the service account.
%NSSM% install %SERVICE% "%CMD_EXE%"
%NSSM% set %SERVICE% AppParameters /c "%RUNNER%"

%NSSM% set %SERVICE% AppDirectory "%PROJECT_DIR%"
%NSSM% set %SERVICE% DisplayName "SmartWagers Daphne ASGI Server"
%NSSM% set %SERVICE% Description "SmartWagers sabong wagering system - Daphne ASGI"
%NSSM% set %SERVICE% Start SERVICE_AUTO_START
%NSSM% set %SERVICE% AppStdout "%LOG_DIR%\daphne_stdout.log"
%NSSM% set %SERVICE% AppStderr "%LOG_DIR%\daphne_stderr.log"
%NSSM% set %SERVICE% AppStdoutCreationDisposition 4
%NSSM% set %SERVICE% AppStderrCreationDisposition 4
%NSSM% set %SERVICE% AppRotateFiles 1
%NSSM% set %SERVICE% AppRotateBytes 10485760
%NSSM% set %SERVICE% AppThrottle 1500
%NSSM% set %SERVICE% AppExit Default Restart
%NSSM% set %SERVICE% AppRestartDelay 5000
%NSSM% set %SERVICE% AppEnvironmentExtra DJANGO_SETTINGS_MODULE=GameFowl.settings

echo.
echo Starting service...
%NSSM% start %SERVICE%
timeout /t 3 /nobreak >nul

for /f "tokens=*" %%s in ('%NSSM% status %SERVICE% 2^>nul') do set _STATE=%%s
echo Service status: %_STATE%

if /i not "%_STATE%"=="SERVICE_RUNNING" (
    echo.
    echo WARNING: Service is not RUNNING.
    echo Check these logs for the real crash reason:
    echo   %LOG_DIR%\daphne_wrapper.log
    echo   %LOG_DIR%\daphne_stderr.log
    echo   %LOG_DIR%\daphne_stdout.log
    echo.
    echo Manual test from an Admin Command Prompt:
    echo   cd /d %PROJECT_DIR%
    echo   python -m daphne -v 2 -b 0.0.0.0 -p 8080 GameFowl.asgi:application
) else (
    echo Service started successfully.
)

echo.
echo Verify: open http://localhost:8080/login in a browser.
echo Wrapper log: %LOG_DIR%\daphne_wrapper.log
echo.
pause
