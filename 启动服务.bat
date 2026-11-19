@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Install Python 3 first, then run this again.
  pause
  exit /b 1
)
python server.py %*
if errorlevel 1 pause
