@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_web.ps1"

if errorlevel 1 (
    echo.
    echo Failed to start the web UI.
    echo Make sure Python 3.10 or newer is installed, then run this file again.
    echo.
    pause
)
