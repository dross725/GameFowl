@echo off
REM ============================================================
REM  SmartWagers — Diagnose Daphne service startup problems
REM  Run from an Administrator Command Prompt.
REM ============================================================

set PROJECT_DIR=C:\SmartWagers\GameFowl
set LOG_DIR=C:\SmartWagers\logs
set PATH_FILE=%PROJECT_DIR%\deploy\python_path.txt

echo.
echo === 1. python_path.txt ===
if exist "%PATH_FILE%" (
    type "%PATH_FILE%"
    echo.
    set /p P=<"%PATH_FILE%"
    echo %P% | find /I "WindowsApps" >nul
    if not errorlevel 1 (
        echo PROBLEM: This is the Windows Store stub.
        echo          Windows services cannot run it - exit code 9020.
        echo          Install Python from https://python.org instead.
    ) else (
        if exist "%P%" (
            echo OK: file exists
            "%P%" --version
        ) else (
            echo PROBLEM: path does not exist on disk
        )
    )
) else (
    echo PROBLEM: %PATH_FILE% not found. Run 4_install_service.bat first.
)

echo.
echo === 2. What does interactive Python report? ===
python -c "import sys; print(sys.executable)" 2>nul
if errorlevel 1 echo python command failed
py -3 -c "import sys; print(sys.executable)" 2>nul
if errorlevel 1 echo py -3 command failed

echo.
echo === 3. Common real Python install locations ===
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
    echo FOUND: %LocalAppData%\Programs\Python\Python312\python.exe
)
if exist "%LocalAppData%\Programs\Python\Python313\python.exe" (
    echo FOUND: %LocalAppData%\Programs\Python\Python313\python.exe
)
if exist "%ProgramFiles%\Python312\python.exe" (
    echo FOUND: %ProgramFiles%\Python312\python.exe
)
if exist "%ProgramFiles%\Python313\python.exe" (
    echo FOUND: %ProgramFiles%\Python313\python.exe
)
if exist "C:\Python312\python.exe" (
    echo FOUND: C:\Python312\python.exe
)

echo.
echo === 4. Is port 8080 already in use? ===
netstat -ano | findstr ":8080"
if errorlevel 1 (
    echo Port 8080 appears free.
) else (
    echo.
    echo Port 8080 is in use. To see which process:
    echo   tasklist /FI "PID eq <pid-from-above>"
)

echo.
echo === 5. Latest wrapper log tail ===
if exist "%LOG_DIR%\daphne_wrapper.log" (
    powershell -NoProfile -Command "Get-Content '%LOG_DIR%\daphne_wrapper.log' -Tail 20"
) else (
    echo No wrapper log yet.
)

echo.
echo === Next steps ===
echo If python_path.txt contains WindowsApps:
echo   1. Install Python 3.12 from https://www.python.org/downloads/
echo      - check "Add python.exe to PATH"
echo      - check "Install for all users" if available
echo   2. Disable Store aliases:
echo      Settings - Apps - Advanced app settings - App execution aliases
echo      Turn OFF "python.exe" and "python3.exe"
echo   3. Open a NEW Command Prompt and run:
echo      python -c "import sys; print(sys.executable)"
echo      ^(must NOT contain WindowsApps^)
echo   4. Put that path alone into:
echo      %PATH_FILE%
echo   5. sc stop SmartWagers-Daphne
echo   6. Re-run 4_install_service.bat as Administrator
echo.
pause
