@echo off
REM ============================================================
REM  SmartWagers — Daphne launcher used by the Windows service.
REM
REM  IMPORTANT: Windows services do NOT inherit the logged-in user's
REM  PATH.  This script therefore uses the absolute python.exe path
REM  written by 4_install_service.bat into python_path.txt.
REM ============================================================

set PROJECT_DIR=C:\SmartWagers\GameFowl
set LOG_DIR=C:\SmartWagers\logs
set WRAPPER_LOG=%LOG_DIR%\daphne_wrapper.log
set DAPHNE_LOG=%LOG_DIR%\daphne_run.log
set PYTHON_PATH_FILE=%~dp0python_path.txt

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo.>> "%WRAPPER_LOG%"
echo ========================================>> "%WRAPPER_LOG%"
echo [%date% %time%] Starting Daphne>> "%WRAPPER_LOG%"
echo PROJECT_DIR=%PROJECT_DIR%>> "%WRAPPER_LOG%"

if not exist "%PYTHON_PATH_FILE%" (
    echo [%date% %time%] ERROR: python_path.txt not found at %PYTHON_PATH_FILE%>> "%WRAPPER_LOG%"
    echo [%date% %time%] Re-run 4_install_service.bat as Administrator.>> "%WRAPPER_LOG%"
    exit /b 1
)

set /p PYTHON_EXE=<"%PYTHON_PATH_FILE%"
echo PYTHON_EXE=%PYTHON_EXE%>> "%WRAPPER_LOG%"

echo %PYTHON_EXE% | find /I "WindowsApps" >nul
if not errorlevel 1 (
    echo [%date% %time%] ERROR: python_path.txt points at the Windows Store stub.>> "%WRAPPER_LOG%"
    echo [%date% %time%] That path cannot run as a Windows service.>> "%WRAPPER_LOG%"
    echo [%date% %time%] Re-run 4_install_service.bat after installing Python from python.org.>> "%WRAPPER_LOG%"
    exit /b 1
)

if not exist "%PYTHON_EXE%" (
    echo [%date% %time%] ERROR: python.exe not found at %PYTHON_EXE%>> "%WRAPPER_LOG%"
    echo [%date% %time%] Re-run 4_install_service.bat as Administrator.>> "%WRAPPER_LOG%"
    exit /b 1
)

"%PYTHON_EXE%" --version >> "%WRAPPER_LOG%" 2>&1

cd /d "%PROJECT_DIR%"
if errorlevel 1 (
    echo [%date% %time%] ERROR: cannot cd to %PROJECT_DIR%>> "%WRAPPER_LOG%"
    exit /b 1
)

set DJANGO_SETTINGS_MODULE=GameFowl.settings

REM Pre-flight inside the service process so failures are logged here.
echo [%date% %time%] Checking daphne import...>> "%WRAPPER_LOG%"
"%PYTHON_EXE%" -c "import daphne; print('daphne OK', daphne.__file__)" >> "%WRAPPER_LOG%" 2>&1
if errorlevel 1 (
    echo [%date% %time%] ERROR: daphne is not installed for this Python.>> "%WRAPPER_LOG%"
    echo [%date% %time%] Run: "%PYTHON_EXE%" -m pip install -r requirements.txt>> "%WRAPPER_LOG%"
    exit /b 1
)

echo [%date% %time%] Checking ASGI import...>> "%WRAPPER_LOG%"
"%PYTHON_EXE%" -c "import GameFowl.asgi; print('ASGI OK')" >> "%WRAPPER_LOG%" 2>&1
if errorlevel 1 (
    echo [%date% %time%] ERROR: GameFowl.asgi failed to import. See traceback above.>> "%WRAPPER_LOG%"
    exit /b 1
)

echo [%date% %time%] Launching Daphne...>> "%WRAPPER_LOG%"
echo [%date% %time%] Full command output is also in %DAPHNE_LOG%>> "%WRAPPER_LOG%"

REM Capture Daphne stdout+stderr so crashes are visible even when NSSM
REM redirection fails.  -u keeps output unbuffered.
"%PYTHON_EXE%" -u -m daphne -v 2 -b 0.0.0.0 -p 8080 GameFowl.asgi:application >> "%DAPHNE_LOG%" 2>&1
set EXITCODE=%ERRORLEVEL%

echo [%date% %time%] Daphne exited with code %EXITCODE%>> "%WRAPPER_LOG%"
echo [%date% %time%] Last lines of daphne_run.log:>> "%WRAPPER_LOG%"
powershell -NoProfile -Command "if (Test-Path '%DAPHNE_LOG%') { Get-Content '%DAPHNE_LOG%' -Tail 40 | ForEach-Object { Add-Content '%WRAPPER_LOG%' $_ } }"
exit /b %EXITCODE%
