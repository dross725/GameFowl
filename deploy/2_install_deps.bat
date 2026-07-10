@echo off
REM ============================================================
REM  SmartWagers — Step 2: Install Python dependencies
REM  Run from the project root: C:\SmartWagers\GameFowl\
REM  Requires Python 3.11+ already installed and on PATH.
REM ============================================================

echo Checking Python version...
python --version
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.12 from https://python.org
    echo        Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

echo.
echo Upgrading pip...
python -m pip install --upgrade pip

echo.
echo Installing project dependencies from requirements.txt...
python -m pip install -r "%~dp0..\requirements.txt"

if errorlevel 1 (
    echo.
    echo ERROR: pip install failed. Check the output above for details.
    pause
    exit /b 1
)

echo.
echo All dependencies installed successfully.
pause
