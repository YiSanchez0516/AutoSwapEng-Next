@echo off
chcp 65001 >nul
title 翻转外语助手 - 诊断
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [错误] 未找到 .venv, 请先双击 install.bat
    pause
    exit /b 1
)
"%PY%" "%ROOT%main.py" doctor
echo.
echo 以上内容已保存到 logs\doctor.txt, 可直接发给我。
pause
