@echo off
cd /d %~dp0
C:\Users\asus\AppData\Local\Programs\Python\Python313\python.exe -m venv .venv
.venv\Scripts\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
pause
