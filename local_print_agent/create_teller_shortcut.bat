@echo off
REM ============================================================
REM  Creates a Desktop shortcut for the silent teller launcher
REM  with the SmartWagers / A. Tabora Sports Club logo icon.
REM
REM  Windows cannot change the icon of a .vbs file itself — the
REM  shortcut (.lnk) is what you pin / put on the desktop.
REM ============================================================

setlocal
set AGENT_DIR=%~dp0
set ICO=%AGENT_DIR%smartwagers.ico
set TARGET=%AGENT_DIR%start_teller_silent.vbs
set NAME=SmartWagers Teller

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
  "$s.WorkingDirectory = '%AGENT_DIR%'; " ^
  "$s.IconLocation = '%ICO%,0'; " ^
  "$s.Description = 'Start SmartWagers teller (print agent + Chrome)'; " ^
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
echo You can pin that shortcut to the taskbar if you want.
echo.
pause
endlocal
