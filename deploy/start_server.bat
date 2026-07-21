@echo off
REM ============================================================
REM  SmartWagers — Server startup
REM  Ensures dependency services are up, then opens Chrome once.
REM
REM  Checks / starts:
REM    1. Memurai  (Redis)     — service + PING
REM    2. Daphne               — Windows service + HTTP :8080
REM    3. Local print agent    — http://127.0.0.1:8765/health
REM
REM  Uses goto-based flow (no CALL inside parenthesized IF blocks).
REM  Set SMARTWAGERS_SILENT=1 (via start_server_silent.vbs) to skip pause.
REM ============================================================

setlocal EnableDelayedExpansion

set NSSM=C:\SmartWagers\nssm\nssm.exe
set SERVICE=SmartWagers-Daphne
set MEMURAI_SERVICE=Memurai
set PROJECT_DIR=C:\SmartWagers\GameFowl
set LOG_DIR=C:\SmartWagers\logs
set PRINT_AGENT_DIR=C:\SmartWagers\local_print_agent
if not exist "%PRINT_AGENT_DIR%\print_agent.py" if exist "%PROJECT_DIR%\local_print_agent\print_agent.py" (
    set "PRINT_AGENT_DIR=%PROJECT_DIR%\local_print_agent"
)
set APP_URL=http://localhost:8080/login
set APP_HEALTH=http://127.0.0.1:8080/login
set PRINT_HEALTH=http://127.0.0.1:8765/health
set DAPHNE_READY=0
set MEMURAI_READY=0
set PRINT_READY=0

echo.
echo ========================================
echo  SmartWagers Server Startup
echo ========================================
echo.

REM ============================================================
REM  1. Memurai (required for WebSockets / Channels)
REM ============================================================
echo [1/3] Memurai...
memurai-cli ping >nul 2>&1
if not errorlevel 1 goto :memurai_ready

echo        Not responding — starting "%MEMURAI_SERVICE%" service...
sc start %MEMURAI_SERVICE% >nul 2>&1

set /a _TRIES=0
:memurai_wait
set /a _TRIES+=1
ping -n 2 127.0.0.1 >nul
memurai-cli ping >nul 2>&1
if not errorlevel 1 goto :memurai_ready
if %_TRIES% LSS 10 goto :memurai_wait

echo        ERROR: Memurai did not respond to PING.
echo        Fix: open services.msc, start "Memurai", then re-run this script.
echo        Or:  memurai-cli ping
if /i not "%SMARTWAGERS_SILENT%"=="1" pause
exit /b 1

:memurai_ready
set MEMURAI_READY=1
echo        OK — Memurai responding.

REM ============================================================
REM  2. Daphne (SmartWagers web + WebSocket server)
REM ============================================================
echo [2/3] Daphne ^(%SERVICE%^)...

REM Already serving HTTP?
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri '%APP_HEALTH%' -UseBasicParsing -TimeoutSec 2; exit 0 } catch { if ($_.Exception.Response) { exit 0 } else { exit 1 } }" >nul 2>&1
if not errorlevel 1 goto :daphne_http_ok

REM Read Windows service state
set "_STATE="
if exist "%NSSM%" (
    for /f "delims=" %%s in ('"%NSSM%" status %SERVICE% 2^>nul') do set "_STATE=%%s"
) else (
    for /f "tokens=3 delims=: " %%s in ('sc query %SERVICE% ^| findstr /I "STATE"') do set "_STATE=%%s"
)
echo        Service status: !_STATE!

REM Already running — wait for HTTP only
echo !_STATE! | find /I "RUNNING" >nul
if not errorlevel 1 goto :daphne_wait_http

REM PAUSED = NSSM crash throttle — must stop then start
echo !_STATE! | find /I "PAUSED" >nul
if errorlevel 1 goto :daphne_start
echo        Service is PAUSED ^(crash throttle^) — clearing...
sc continue %SERVICE% >nul 2>&1
ping -n 2 127.0.0.1 >nul
if exist "%NSSM%" (
    "%NSSM%" stop %SERVICE% >nul 2>&1
) else (
    sc stop %SERVICE% >nul 2>&1
)
ping -n 3 127.0.0.1 >nul

:daphne_start
echo        Starting %SERVICE%...
if exist "%NSSM%" (
    "%NSSM%" start %SERVICE% >nul 2>&1
) else (
    sc start %SERVICE% >nul 2>&1
)

:daphne_wait_http
echo        Waiting for http://127.0.0.1:8080 ...
set /a _TRIES=0
:daphne_http_loop
set /a _TRIES+=1
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri '%APP_HEALTH%' -UseBasicParsing -TimeoutSec 2; exit 0 } catch { if ($_.Exception.Response) { exit 0 } else { exit 1 } }" >nul 2>&1
if not errorlevel 1 goto :daphne_http_ok
if %_TRIES% GEQ 20 goto :daphne_http_fail
ping -n 2 127.0.0.1 >nul
goto :daphne_http_loop

:daphne_http_fail
echo        ERROR: Daphne service did not become ready on port 8080.
set "_STATE="
if exist "%NSSM%" (
    for /f "delims=" %%s in ('"%NSSM%" status %SERVICE% 2^>nul') do set "_STATE=%%s"
)
echo        Final service status: !_STATE!
echo        Logs: %LOG_DIR%\daphne_wrapper.log
echo              %LOG_DIR%\daphne_run.log
echo        Tip: run deploy\diagnose_service.bat as Administrator
echo             or: deploy\service_control.bat start
if /i not "%SMARTWAGERS_SILENT%"=="1" pause
exit /b 1

:daphne_http_ok
set DAPHNE_READY=1
echo        OK — Daphne listening on :8080.

REM ============================================================
REM  3. Local print agent (optional on server PC, recommended)
REM ============================================================
echo [3/3] Local print agent...
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri '%PRINT_HEALTH%' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 goto :print_ok

if not exist "%PRINT_AGENT_DIR%\print_agent.py" goto :print_missing

echo        Not running — starting...
if exist "%PRINT_AGENT_DIR%\start_print_agent_silent.vbs" (
    wscript //nologo "%PRINT_AGENT_DIR%\start_print_agent_silent.vbs"
) else (
    where pythonw >nul 2>&1
    if not errorlevel 1 (
        start "" /D "%PRINT_AGENT_DIR%" pythonw print_agent.py
    ) else (
        start "" /D "%PRINT_AGENT_DIR%" /min python print_agent.py
    )
)

set /a _TRIES=0
:print_wait
set /a _TRIES+=1
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri '%PRINT_HEALTH%' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 goto :print_ok
if %_TRIES% GEQ 8 goto :print_warn
ping -n 2 127.0.0.1 >nul
goto :print_wait

:print_warn
echo        WARNING: Print agent did not respond at %PRINT_HEALTH%
echo        Receipt printing on this PC may not work.
goto :print_done

:print_missing
echo        WARNING: print_agent.py not found at %PRINT_AGENT_DIR%
echo        Install with local_print_agent\install_print_agent.bat if needed.
goto :print_done

:print_ok
set PRINT_READY=1
echo        OK — Print agent healthy.

:print_done

REM ============================================================
REM  Summary + Chrome (only if Daphne is ready)
REM ============================================================
echo.
echo ----------------------------------------
echo  Ready check
echo    Memurai:      %MEMURAI_READY%
echo    Daphne :8080: %DAPHNE_READY%
echo    Print agent:  %PRINT_READY%
echo ----------------------------------------
echo.

if not "%DAPHNE_READY%"=="1" (
    echo ERROR: Daphne is not ready — Chrome will not open.
    if /i not "%SMARTWAGERS_SILENT%"=="1" pause
    exit /b 1
)

echo Opening Chrome: %APP_URL%
set "CHROME_EXE="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%LocalAppData%\Google\Chrome\Application\chrome.exe"

if defined CHROME_EXE goto :chrome_exe
start "SmartWagers" "%APP_URL%"
goto :chrome_done

:chrome_exe
start "SmartWagers" "%CHROME_EXE%" "%APP_URL%"

:chrome_done
echo Done.
if /i not "%SMARTWAGERS_SILENT%"=="1" timeout /t 2 /nobreak >nul
endlocal
exit /b 0
