@echo off
REM ============================================================
REM  SmartWagers — Teller / cashier PC startup
REM  Starts print agent if needed; opens Chrome once to server URL.
REM
REM  Uses goto-based flow (no CALL inside parenthesized IF blocks).
REM ============================================================

setlocal EnableDelayedExpansion

set AGENT_DIR=%~dp0
set PRINT_HEALTH=http://127.0.0.1:8765/health
set SERVER_URL=
set ENV_FILE=

echo.
echo ========================================
echo  SmartWagers Teller Startup
echo ========================================
echo.

if exist "%AGENT_DIR%server.env" set "ENV_FILE=%AGENT_DIR%server.env"
if not defined ENV_FILE if exist "%AGENT_DIR%.env" set "ENV_FILE=%AGENT_DIR%.env"
if not defined ENV_FILE if exist "C:\SmartWagers\GameFowl\.env" set "ENV_FILE=C:\SmartWagers\GameFowl\.env"

if defined ENV_FILE goto :env_found
echo ERROR: No server.env or .env found.
echo.
echo Create %AGENT_DIR%server.env with one line:
echo   SMARTWAGERS_SERVER_URL=http://192.168.1.10:8080
if /i not "%SMARTWAGERS_SILENT%"=="1" pause
exit /b 1

:env_found
echo Using config: %ENV_FILE%

for /f "usebackq tokens=1,* delims==" %%a in (`findstr /B /I /C:"SMARTWAGERS_SERVER_URL=" "%ENV_FILE%"`) do set "SERVER_URL=%%b"
for /f "tokens=* delims= " %%u in ("%SERVER_URL%") do set "SERVER_URL=%%u"

if defined SERVER_URL goto :url_found
echo ERROR: SMARTWAGERS_SERVER_URL not set in %ENV_FILE%
echo Add: SMARTWAGERS_SERVER_URL=http://192.168.1.10:8080
if /i not "%SMARTWAGERS_SILENT%"=="1" pause
exit /b 1

:url_found
echo %SERVER_URL% | findstr /I /C:"/login" >nul
if not errorlevel 1 goto :url_ready
if "%SERVER_URL:~-1%"=="/" (
    set "SERVER_URL=%SERVER_URL%login"
) else (
    set "SERVER_URL=%SERVER_URL%/login"
)

:url_ready
echo Server URL: %SERVER_URL%
echo.

REM ---------- Print agent ----------
echo [1/2] Checking local print agent...
set PRINT_OK=0
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri '%PRINT_HEALTH%' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 set PRINT_OK=1
if "%PRINT_OK%"=="1" goto :print_ok

echo        Starting print agent...
if not exist "%AGENT_DIR%print_agent.py" goto :print_missing
if exist "%AGENT_DIR%start_print_agent_silent.vbs" (
    wscript //nologo "%AGENT_DIR%start_print_agent_silent.vbs"
) else if exist "%AGENT_DIR%python\pythonw.exe" (
    start "" /D "%AGENT_DIR%" "%AGENT_DIR%python\pythonw.exe" print_agent.py
) else if exist "%AGENT_DIR%python\python.exe" (
    start "" /D "%AGENT_DIR%" /min "%AGENT_DIR%python\python.exe" print_agent.py
) else (
    where pythonw >nul 2>&1
    if not errorlevel 1 (
        start "" /D "%AGENT_DIR%" pythonw print_agent.py
    ) else (
        start "" /D "%AGENT_DIR%" /min python print_agent.py
    )
)
set PRINT_OK=0
set /a _TRIES=0
:print_wait
set /a _TRIES+=1
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri '%PRINT_HEALTH%' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 set PRINT_OK=1
if "%PRINT_OK%"=="1" goto :print_ok
if %_TRIES% GEQ 8 goto :print_wait_done
ping -n 2 127.0.0.1 >nul
goto :print_wait
:print_wait_done
echo        WARNING: Print agent did not respond at %PRINT_HEALTH%
goto :print_done

:print_missing
echo        ERROR: print_agent.py not found in %AGENT_DIR%
if /i not "%SMARTWAGERS_SILENT%"=="1" pause
exit /b 1

:print_ok
echo        Print agent OK.

:print_done

REM ---------- Chrome (exactly once) ----------
echo [2/2] Opening Chrome...
set "CHROME_EXE="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%LocalAppData%\Google\Chrome\Application\chrome.exe"

if defined CHROME_EXE goto :chrome_exe
start "SmartWagers" "%SERVER_URL%"
goto :chrome_done

:chrome_exe
start "SmartWagers" "%CHROME_EXE%" "%SERVER_URL%"

:chrome_done
echo.
echo Done.
timeout /t 2 /nobreak >nul
endlocal
exit /b 0
