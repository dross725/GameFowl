@echo off
REM ============================================================
REM  Creates a Desktop shortcut for the silent server launcher
REM  with the SmartWagers / A. Tabora Sports Club logo icon.
REM ============================================================

setlocal
set DEPLOY_DIR=%~dp0
set ICO=%DEPLOY_DIR%smartwagers.ico
set TARGET=%DEPLOY_DIR%start_server_silent.vbs
set NAME=SmartWagers Server

if not exist "%ICO%" (
    echo ERROR: Icon not found: %ICO%
    pause
    exit /b 1
)
if not exist "%TARGET%" (
    echo ERROR: Launcher not found: %TARGET%
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$desktop = [Environment]::GetFolderPath('Desktop'); " ^
  "$lnkPath = Join-Path $desktop '%NAME%.lnk'; " ^
  "$s = $ws.CreateShortcut($lnkPath); " ^
  "$s.TargetPath = 'wscript.exe'; " ^
  "$s.Arguments = '//nologo ""%TARGET%""'; " ^
  "$s.WorkingDirectory = '%DEPLOY_DIR%'; " ^
  "$s.IconLocation = '%ICO%,0'; " ^
  "$s.Description = 'Start SmartWagers server (Memurai + Daphne + print agent + Chrome)'; " ^
  "$s.WindowStyle = 7; " ^
  "$s.Save(); " ^
  "Write-Host ('Shortcut created: ' + $lnkPath)"

if errorlevel 1 (
    echo ERROR: Failed to create shortcut.
    pause
    exit /b 1
)

echo.
echo Done. Use the "%NAME%" icon on your Desktop.
echo.
pause
endlocal
