@echo off
chcp 65001 >nul
title 翻转外语自动化助手
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [错误] 未找到 .venv, 请先双击 install.bat 安装依赖
    pause
    exit /b 1
)
"%PY%" "%ROOT%main.py" %*
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
    echo.
    echo [错误] 程序异常退出, 退出码 %CODE%
    echo 详细日志: "%ROOT%logs\crash.log"
)
if "%~1"=="" pause
exit /b %CODE%
