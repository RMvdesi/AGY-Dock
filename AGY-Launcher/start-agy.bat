@echo off
cd /d "D:\Documents\codex\agy plugins mannager\AGY-Launcher"
rem 使用 wscript 无窗包装执行 Node CLI 启动，避免控制台闪框
start "" wscript.exe "D:\Documents\codex\agy plugins mannager\AGY-Launcher\launch-silent.vbs"
exit /b 0
