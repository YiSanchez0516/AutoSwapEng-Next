# 一键安装: Python 3.12 + 虚拟环境 + PaddleOCR (Windows, 用户级)
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

$python = Find-Python312
if (-not $python) {
    Write-Host "未找到 Python 3.12, 正在通过 winget 安装..." -ForegroundColor Yellow
    winget install --id Python.Python.3.12 -e --scope user `
        --accept-package-agreements --accept-source-agreements --disable-interactivity
    $python = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    if (-not (Test-Path $python)) { throw "Python 3.12 安装失败, 请手动安装后重试" }
}

if (-not (Test-Path $Venv)) {
    Write-Host "创建虚拟环境: $Venv" -ForegroundColor Cyan
    & $python -m venv $Venv
}

$venvPython = Join-Path $Venv "Scripts\python.exe"
Write-Host "升级 pip..." -ForegroundColor Cyan
& $venvPython -m pip install --upgrade pip -i $Mirror

Write-Host "安装 PaddleOCR 依赖 (首次约几百 MB)..." -ForegroundColor Cyan
& $venvPython -m pip install -r (Join-Path $Root "requirements.txt") -i $Mirror

Write-Host ""
Write-Host "安装完成。" -ForegroundColor Green
Write-Host "下一步:"
Write-Host "  1) 打开投屏软件 (Escrcpy / scrcpy / 模拟器), 让翻转外语画面显示出来"
Write-Host "  2) 双击 run.bat, 选择 1 框选投屏窗口"
Write-Host "  3) 选择 3 抓屏诊断, 确认 OCR 能读清题目"
Write-Host "  4) 选择 2 开始自动答题"
Write-Host ""
Write-Host "首次 OCR 运行会自动下载中文模型 (约 20MB)."
