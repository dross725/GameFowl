@echo off
REM ============================================================
REM  SmartWagers — Install the local print agent on this PC
REM  Run this on each Windows cashier/teller PC.
REM
REM  What it does:
REM    1. Uses bundled python\ (embeddable 3.12 + pywin32) when present
REM    2. Verifies pywin32 / shows Windows default printer
REM    3. Creates config.json from the example if not present
REM    4. Adds a silent VBS launcher to Windows Startup
REM
REM  Offline: no pip / no internet required when python\ is bundled.
REM ============================================================

setlocal EnableDelayedExpansion
set AGENT_DIR=%~dp0
set PY=
set PYW=

REM -- Prefer bundled embeddable Python
if exist "%AGENT_DIR%python\python.exe" (
    set "PY=%AGENT_DIR%python\python.exe"
    if exist "%AGENT_DIR%python\pythonw.exe" set "PYW=%AGENT_DIR%python\pythonw.exe"
    echo Using bundled Python: %AGENT_DIR%python\python.exe
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Bundled Python not found at:
        echo        %AGENT_DIR%python\python.exe
        echo.
        echo        Re-download the Print Agent package from Admin -^> Print Agent
        echo        ^(server must run prepare_vendor.bat first^), or place a full
        echo        offline package that includes the python\ folder.
        echo.
        echo        System Python was also not found on PATH.
        pause
        exit /b 1
    )
    for /f "delims=" %%P in ('where python') do (
        if not defined PY set "PY=%%P"
    )
    echo WARNING: Bundled python\ missing — falling back to system Python:
    echo          !PY!
    echo          Offline installs should use the Admin download package.
    where pythonw >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%W in ('where pythonw') do (
            if not defined PYW set "PYW=%%W"
        )
    )
)

echo.
"%PY%" -c "import sys; print(sys.version)"
if errorlevel 1 (
    echo ERROR: Could not run Python: %PY%
    pause
    exit /b 1
)

REM -- Verify pywin32 (do NOT pip install from the network)
echo.
echo Verifying pywin32...
"%PY%" -c "import win32print, win32con; print('win32print/win32con: OK')"
if errorlevel 1 (
    echo pywin32 import failed — trying post-install...
    "%PY%" -m pywin32_postinstall -install
    if errorlevel 1 (
        if exist "%AGENT_DIR%python\Scripts\pywin32_postinstall.py" (
            "%PY%" "%AGENT_DIR%python\Scripts\pywin32_postinstall.py" -install
        )
    )
    "%PY%" -c "import win32print, win32con; print('win32print/win32con: OK')"
    if errorlevel 1 (
        echo ERROR: pywin32 is missing or broken for this Python.
        echo        Re-download the Print Agent zip after running prepare_vendor.bat
        echo        on the server, or reinstall the offline package.
        pause
        exit /b 1
    )
)

"%PY%" -c "import win32ui; print('win32ui: OK')"
if errorlevel 1 (
    echo.
    echo WARNING: win32ui DLL failed to load.
    echo This usually needs:
    echo   1. Microsoft Visual C++ Redistributable ^(x64^)
    echo   2. Or set "print_mode": "escpos" in config.json for thermal printers
    echo      ^(escpos uses win32print only, not win32ui^)
    echo.
) else (
    echo win32ui: OK
)

if defined PYW (
    "%PYW%" -c "import win32print, win32con" 2>nul
    if errorlevel 1 (
        echo WARNING: pythonw cannot import pywin32. Silent start may fail.
    ) else (
        echo pythonw: OK
    )
)

REM -- Show Windows default printer (no need to type the name)
echo.
echo ---------- Printers ----------
"%PY%" -c "import win32print; d=win32print.GetDefaultPrinter(); print('Windows default printer:'); print(' ', d or '(none set)'); print('Installed printers:'); flags=win32print.PRINTER_ENUM_LOCAL|win32print.PRINTER_ENUM_CONNECTIONS; [print(' -', p[2]) for p in win32print.EnumPrinters(flags)]"
echo.
echo The print agent uses the Windows default printer when config.json
echo has "printer_name": "" ^(recommended^).
echo Set printer_name only if the receipt printer is NOT the Windows default.
echo ------------------------------
echo.

REM -- Create config.json if it does not already exist
if not exist "%AGENT_DIR%config.json" (
    echo Creating config.json from template...
    copy "%AGENT_DIR%config.example.json" "%AGENT_DIR%config.json" >nul
    echo Created %AGENT_DIR%config.json
    echo printer_name left empty — will use Windows default.
) else (
    echo config.json already exists — skipping copy.
)

REM -- Add silent launcher to Windows Startup (no CMD window on login)
set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set SHORTCUT=%STARTUP%\SmartWagers-PrintAgent.vbs
set OLD_BAT=%STARTUP%\SmartWagers-PrintAgent.bat

echo.
echo Adding print agent to Windows Startup folder (silent)...
if exist "%OLD_BAT%" del "%OLD_BAT%"
if not exist "%AGENT_DIR%start_print_agent_silent.vbs" (
    echo ERROR: start_print_agent_silent.vbs missing from %AGENT_DIR%
    pause
    exit /b 1
)
(
echo ' Auto-generated by install_print_agent.bat - runs print agent hidden
echo Set sh = CreateObject^("WScript.Shell"^)
echo sh.Run "wscript.exe //nologo ""%AGENT_DIR%start_print_agent_silent.vbs""", 0, False
) > "%SHORTCUT%"

echo.
echo Done. The print agent will start automatically on next login ^(no window^).
echo.
echo To start it now ^(background^):
echo   %AGENT_DIR%run_print_agent.bat
echo.
echo To test: open http://127.0.0.1:8765/health in a browser on this PC.
echo.
pause
endlocal
exit /b 0
