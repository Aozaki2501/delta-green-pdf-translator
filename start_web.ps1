$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $Python = $VenvPython
} else {
    $Python = "python"
}

Write-Host ""
Write-Host "Starting Delta Green PDF Translator Web UI..."
Write-Host "Project: $ProjectRoot"
Write-Host "URL: http://localhost:8501"
Write-Host ""

& $Python -m streamlit run app.py --server.port 8501
