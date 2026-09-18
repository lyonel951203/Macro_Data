@echo off
setlocal
cd /d "%~dp0"
if exist "reports\v2\daily_global_update\latest.md" (
  type "reports\v2\daily_global_update\latest.md"
) else (
  echo No daily global update report exists yet.
)
