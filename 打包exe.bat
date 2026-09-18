@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [提示] 还没安装运行环境，找不到 .venv。
    echo        请先双击「安装环境.bat」，装完再运行本脚本。
    pause
    exit /b 1
)
if not exist ".venv\Lib\site-packages\PyInstaller" (
    echo [错误] 当前 .venv 缺少 PyInstaller，无法打包。
    echo        请重新运行「安装环境.bat」。
    pause
    exit /b 1
)
echo 正在打包（约 1 分钟，请勿关闭窗口）...
.venv\Scripts\python.exe build\build.py %*
echo.
if errorlevel 1 (
    echo [错误] 打包失败，请把上面的输出发给开发者。
) else (
    echo 打包完成，exe 在 dist\ 目录。
)
pause
