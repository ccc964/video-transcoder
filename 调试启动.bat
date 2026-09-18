@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [提示] 还没安装运行环境，找不到 .venv。
    echo        请先双击「安装环境.bat」，装完再运行本脚本。
    pause
    exit /b 1
)
.venv\Scripts\python.exe main.py
if errorlevel 1 pause
