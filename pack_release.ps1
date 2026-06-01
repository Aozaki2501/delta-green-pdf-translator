$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$distDir = Join-Path $ProjectRoot "dist"
New-Item -ItemType Directory -Path $distDir -Force | Out-Null

function Get-Git {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) { throw "git not found." }
    return $git.Source
}

$gitExe = Get-Git
$sha = (& $gitExe rev-parse --short HEAD).Trim()
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$zipName = "DGtranslate-$stamp-$sha.zip"
$zipPath = Join-Path $distDir $zipName

if (Test-Path $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}

Write-Host "Packing release from HEAD..."
& $gitExe archive --format zip --output $zipPath HEAD

Write-Host ""
Write-Host "Done:"
Write-Host $zipPath
Write-Host ""
Write-Host "On your friend's Windows machine:"
Write-Host "1) Unzip"
Write-Host "2) Double-click start_web.bat"
Write-Host ""
