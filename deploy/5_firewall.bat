@echo off
REM ============================================================
REM  SmartWagers — Step 5: Open Windows Firewall for port 8000
REM  Run as Administrator.
REM ============================================================

echo Adding Windows Firewall inbound rule for SmartWagers (port 8000)...

netsh advfirewall firewall show rule name="SmartWagers-Daphne" >nul 2>&1
if not errorlevel 1 (
    echo Rule already exists. Removing old rule first...
    netsh advfirewall firewall delete rule name="SmartWagers-Daphne"
)

netsh advfirewall firewall add rule ^
    name="SmartWagers-Daphne" ^
    dir=in ^
    action=allow ^
    protocol=TCP ^
    localport=8000 ^
    description="Allow LAN access to SmartWagers wagering system"

if errorlevel 1 (
    echo ERROR: Failed to add firewall rule. Are you running as Administrator?
    pause
    exit /b 1
)

echo.
echo Firewall rule added. LAN clients can now reach port 8000.
echo Test from another PC: http://<SERVER-IP>:8000/login
echo.
pause
