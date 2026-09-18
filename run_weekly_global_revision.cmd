@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHON_EXE="
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not defined PYTHON_EXE if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PYTHON_EXE for /f "delims=" %%I in ('where python 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%I"
if not defined PYTHON_EXE exit /b 9009
if not exist "logs\weekly_global_revision" mkdir "logs\weekly_global_revision"
"%PYTHON_EXE%" -u "scripts\run_with_live_log.py" --log "logs\weekly_global_revision\launcher.log" -- "%PYTHON_EXE%" -u "scripts\run_daily_web_update.py" --config "config\weekly_global_revision.yml" --allow-network --lock-wait-seconds 10800
exit /b %ERRORLEVEL%
