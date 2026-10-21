@echo off
REM Apply a release that was already copied into the project tree.
REM Fleet and USB installs should use apply_usb_release.py instead. This wrapper
REM remains for older sync jobs and adds a database backup around migrations.
setlocal
cd /d "%~dp0.."
set PROJECT_DIR=%CD%
set PYTHON_PATH_FILE=%PROJECT_DIR%\deploy\python_path.txt
set PYTHON_EXE=python
if exist "%PYTHON_PATH_FILE%" set /p PYTHON_EXE=<"%PYTHON_PATH_FILE%"
"%PYTHON_EXE%" "%PROJECT_DIR%\deploy\apply_engine.py" --legacy-manifest --target "%PROJECT_DIR%"
exit /b %ERRORLEVEL%
