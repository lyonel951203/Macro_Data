@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
if "%~2"=="" (
  echo Usage: query_pit_wide.cmd T SCOPE [M^|Q] [OUTPUT_PREFIX]
  echo Example: query_pit_wide.cmd 2026-07-31 CN Q
  echo SCOPE: CN, US, or GLB
  echo FREQUENCY: M or Q; defaults to M
  exit /b 2
)
set "FREQUENCY=M"
set "OUTPUT_PREFIX="
if "%~3"=="" goto run_query
if /I "%~3"=="M" (
  set "FREQUENCY=M"
) else if /I "%~3"=="Q" (
  set "FREQUENCY=Q"
) else (
  set "OUTPUT_PREFIX=%~3"
)
if not "%~4"=="" set "OUTPUT_PREFIX=%~4"

:run_query
if "%OUTPUT_PREFIX%"=="" (
  python -m macro_pit query-wide --as-of "%~1" --scope "%~2" --frequency "%FREQUENCY%"
) else (
  python -m macro_pit query-wide --as-of "%~1" --scope "%~2" --frequency "%FREQUENCY%" --output-prefix "%OUTPUT_PREFIX%"
)
exit /b %ERRORLEVEL%