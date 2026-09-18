@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "SCOPE=%~1"
set "START_DATE=%~2"
set "END_DATE=%~3"
set "OUTPUT_PREFIX=%~4"
if "%SCOPE%"=="" set "SCOPE=CN"
if "%START_DATE%"=="" set "START_DATE=2005-01-01"

if "%END_DATE%"=="" (
  if "%OUTPUT_PREFIX%"=="" (
    python -m macro_pit export-long --scope "%SCOPE%" --start-date "%START_DATE%"
  ) else (
    python -m macro_pit export-long --scope "%SCOPE%" --start-date "%START_DATE%" --output-prefix "%OUTPUT_PREFIX%"
  )
) else (
  if "%OUTPUT_PREFIX%"=="" (
    python -m macro_pit export-long --scope "%SCOPE%" --start-date "%START_DATE%" --end-date "%END_DATE%"
  ) else (
    python -m macro_pit export-long --scope "%SCOPE%" --start-date "%START_DATE%" --end-date "%END_DATE%" --output-prefix "%OUTPUT_PREFIX%"
  )
)
exit /b %ERRORLEVEL%