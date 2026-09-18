@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   视频转码 - 安装环境（仅需一次）
echo ============================================
echo.

rem ---- 找一个「自带 tkinter」的 Python ----
rem 本程序是图形界面，必须有 tkinter。部分 Python（微软商店版、精简版、
rem 某些软件自带的 Python）不含 tkinter，直接拿来建 venv 会导致启动即报错。
set "PYEXE="
for %%C in ("py -3.13" "py -3.12" "py -3.11" "py -3.10" "py -3" "python") do (
    if not defined PYEXE (
        %%~C -c "import tkinter" >nul 2>nul && set "PYEXE=%%~C"
    )
)

if not defined PYEXE (
    echo [错误] 没有找到「自带 tkinter 的 Python 3.10+」。
    echo.
    echo        本程序是图形界面，必须有 tkinter 才能运行。
    echo        常见原因：装的是微软商店版/精简版 Python，或 PATH 里第一个
    echo        python 来自其他软件（某些 AI 工具、conda 精简环境等）。
    echo.
    echo        解决：到 https://www.python.org/downloads/ 下载官方安装包，
    echo              安装时勾选 "Add Python to PATH"，然后重跑本脚本。
    echo.
    echo        当前 PATH 里的 python 位置：
    where python 2>nul
    pause
    exit /b 1
)

echo [1/2] 使用 %PYEXE% 创建虚拟环境 .venv ...
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -c "import tkinter" >nul 2>nul
    if errorlevel 1 (
        echo       已有 .venv 不含 tkinter，正在重建 ...
        rmdir /s /q ".venv"
    )
)
if not exist ".venv\Scripts\python.exe" (
    %PYEXE% -m venv .venv
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
echo 校验环境 ...
.venv\Scripts\python.exe -c "import tkinter, PIL, tkinterdnd2; print('  tkinter OK / pillow OK / tkinterdnd2 OK')"
if errorlevel 1 (
    echo [错误] 环境校验未通过
    pause
    exit /b 1
)
.venv\Scripts\python.exe main.py --smoke "%TEMP%\vt_smoke.txt" >nul 2>nul
if errorlevel 1 (
    echo [警告] 自检未全部通过，详情见 %TEMP%\vt_smoke.txt
)

echo.
echo 安装完成，双击「启动程序.bat」即可开界面。
pause
