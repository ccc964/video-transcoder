@echo off
cd /d %~dp0
.venv\Scripts\python.exe build\build.py
pause
