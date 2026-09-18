@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   视频转码 - 安装环境（仅需一次）
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 python。
    echo        请先安装 Python 3.10+，安装时务必勾选 "Add Python to PATH"。
    echo        下载：https://www.python.org/downloads/
    pause
    exit /b 1
)

if exist ".venv\Scripts\python.exe" (
    echo [1/2] 已存在 .venv，跳过创建
) else (
    echo [1/2] 创建虚拟环境 .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
)

echo [2/2] 安装依赖 ...
.venv\Scripts\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络
    pause
    exit /b 1
)

echo.
echo 安装完成，双击「启动程序.bat」即可开界面。
pause
