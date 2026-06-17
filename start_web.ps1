$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$Requirements = Join-Path $ProjectRoot "requirements.txt"
if (-not (Test-Path $Requirements)) {
    throw "requirements.txt not found."
}

$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

function Test-PythonVersion {
    param(
        [string]$Executable,
        [string[]]$Arguments = @()
    )

    & $Executable @Arguments -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
    return $LASTEXITCODE -eq 0
}

function Get-BasePython {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher -and (Test-PythonVersion -Executable $pyLauncher.Source -Arguments @("-3"))) {
        return @($pyLauncher.Source, "-3")
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python -and (Test-PythonVersion -Executable $python.Source)) {
        return @($python.Source)
    }

    throw "Python 3.10+ was not found. Install Python 3.10 or newer once, then run start_web.bat again."
}

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating local Python environment..."
    $basePython = Get-BasePython
    if ($basePython.Length -gt 1) {
        & $basePython[0] $basePython[1] -m venv $VenvDir
    } else {
        & $basePython[0] -m venv $VenvDir
    }
}

if (-not (Test-Path $VenvPython)) {
    throw "Failed to create .venv."
}

if (-not (Test-PythonVersion -Executable $VenvPython)) {
    throw "Existing .venv uses Python older than 3.10. Delete .venv after installing Python 3.10+, then run start_web.bat again."
}

$ReqHash = (Get-FileHash $Requirements -Algorithm SHA256).Hash
$StampFile = Join-Path $VenvDir ".requirements.sha256"
$InstalledHash = ""
if (Test-Path $StampFile) {
    $InstalledHash = (Get-Content $StampFile -Raw).Trim()
}

if ($InstalledHash -ne $ReqHash) {
    Write-Host "Installing project dependencies..."
    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install -r $Requirements
    Set-Content -Path $StampFile -Value $ReqHash -Encoding ASCII
}

Write-Host ""
Write-Host "Starting Delta Green PDF Translator Web UI..."
Write-Host "Project: $ProjectRoot"
Write-Host "URL: http://localhost:8501"
Write-Host ""

& $VenvPython -m streamlit run app.py --server.port 8501 --server.headless false
