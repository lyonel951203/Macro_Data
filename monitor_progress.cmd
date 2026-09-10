@echo off
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHONIOENCODING=utf-8"
"C:\Users\71871\AppData\Local\Programs\Python\Python311\python.exe" -u scripts\monitor_source_progress.py --watch 5
