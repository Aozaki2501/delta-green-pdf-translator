@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_web.ps1"

if errorlevel 1 (
    echo.
    echo Failed to start the web UI.
    echo If dependencies are missing, run:
    echo python -m pip install pymupdf openai python-docx streamlit
    echo.
    pause
)
