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
    echo        Do NOT use Python 3.14 with Django 5.1.
    pause
    exit /b 1
)

for /f "delims=" %%i in ('python -c "import sys; print(sys.executable)" 2^>nul') do set PYTHON_EXE=%%i
echo Using interpreter: %PYTHON_EXE%
echo %PYTHON_EXE% | find /I "WindowsApps" >nul
if not errorlevel 1 (
    echo ERROR: PATH points at the Windows Store stub. Install from python.org.
    pause
    exit /b 1
)

REM Warn if Python 3.14+ (Django 5.1 admin is broken without our settings patch)
for /f "delims=" %%v in ('python -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"') do set PY_VER=%%v
echo Detected Python %PY_VER%
echo %PY_VER% | findstr /B "3.14 3.15 3.16" >nul
if not errorlevel 1 (
    echo.
    echo WARNING: Python %PY_VER% is not officially supported by Django 5.1.
    echo          Prefer Python 3.12 for production. Continuing anyway...
    echo.
)
echo.
echo Upgrading pip...
"%PYTHON_EXE%" -m pip install --upgrade pip

echo.
echo Installing project dependencies from requirements.txt...
"%PYTHON_EXE%" -m pip install -r "%~dp0..\requirements.txt"

if errorlevel 1 (
    echo.
    echo ERROR: pip install failed. Check the output above for details.
    pause
    exit /b 1
)

echo.
echo All dependencies installed successfully.
pause
