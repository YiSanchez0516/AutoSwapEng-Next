# One-click installer: Python 3.12 + venv + PaddleOCR (Windows, per-user)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root ".venv"
$Mirror = "https://pypi.tuna.tsinghua.edu.cn/simple"

function Find-Python312 {
    try {
        $exe = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Path $exe.Trim())) {
            return $exe.Trim()
        }
    } catch { }
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "C:\Python312\python.exe",
        "C:\Program Files\Python312\python.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

Write-Host "=== AutoSwapEng-Next installer ===" -ForegroundColor Cyan

$python = Find-Python312
if (-not $python) {
    Write-Host "Python 3.12 not found. Installing via winget..." -ForegroundColor Yellow
    winget install --id Python.Python.3.12 -e --scope user `
        --accept-package-agreements --accept-source-agreements --disable-interactivity
    $python = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    if (-not (Test-Path $python)) {
        throw "Python 3.12 installation failed. Install it manually and run again."
    }
}
Write-Host "Python: $python"

if (-not (Test-Path $Venv)) {
    Write-Host "Creating virtual environment: $Venv" -ForegroundColor Cyan
    & $python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "Failed to create the virtual environment." }
}

$venvPython = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $venvPython)) { throw "venv is incomplete: $venvPython" }

Write-Host "Upgrading pip..." -ForegroundColor Cyan
& $venvPython -m pip install --upgrade pip -i $Mirror
if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade pip." }

Write-Host "Installing PaddleOCR dependencies (several hundred MB on first run)..." -ForegroundColor Cyan
& $venvPython -m pip install -r (Join-Path $Root "requirements.txt") -i $Mirror
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed. Check your network and retry." }

Write-Host ""
Write-Host "Installation complete." -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  1) Open your phone mirroring app (OPPO Connect / scrcpy / emulator) and show Fanzhuan Waiyu"
Write-Host "  2) Double-click run.bat, then choose 1 to select the mirror window"
Write-Host "  3) Choose 3 to capture a frame and verify OCR"
Write-Host "  4) Choose 2 to start"
Write-Host ""
Write-Host "The Chinese OCR model (~20 MB) is downloaded automatically on the first OCR run."
