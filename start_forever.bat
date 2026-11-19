@echo off
cd /d "%~dp0"
title B站钢指直播记录器 - 常驻
:loop
python monitor.py collect
echo [launcher] 采集进程退出，10秒后自动重启...
timeout /t 10 /nobreak >nul
goto loop
