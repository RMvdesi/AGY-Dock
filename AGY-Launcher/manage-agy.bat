@echo off
cd /d "D:\Documents\codex\agy plugins mannager\AGY-Launcher"
title AGY-Launcher 插件管理控制台

:MENU
cls
echo ==================================================
echo        AGY-Launcher 统一启动与插件管理工具
echo ==================================================
echo  1. 打开原生桌面控制程序 (GUI)
echo  2. 查看当前状态 (status)
echo  3. 热附着到当前窗口 (attach)
echo  4. 完整启动客户端与插件 (launch)
echo  5. 停止所有托管插件 (stop)
echo  6. 生成桌面快捷方式 (shortcut)
echo  7. 启动后台守护服务 (daemon)
echo  8. 查看启动器日志 (logs\launcher.log)
echo  0. 退出
echo ==================================================
set /p choice=请输入选项编号 [0-8]: 

if "%choice%"=="1" goto DO_OPEN_UI
if "%choice%"=="2" goto DO_STATUS
if "%choice%"=="3" goto DO_ATTACH
if "%choice%"=="4" goto DO_LAUNCH
if "%choice%"=="5" goto DO_STOP
if "%choice%"=="6" goto DO_SHORTCUT
if "%choice%"=="7" goto DO_DAEMON
if "%choice%"=="8" goto DO_LOGS
if "%choice%"=="0" goto DO_EXIT
echo 无效选项，请重新输入。
pause
goto MENU

:DO_OPEN_UI
start "" "C:\Users\HaoAn\AppData\Local\Programs\Python\Python311\pythonw.exe" "D:\Documents\codex\agy plugins mannager\AGY-Launcher\desktop_app.py"
pause
goto MENU

:DO_STATUS
node.exe "D:\Documents\codex\agy plugins mannager\AGY-Launcher\cli.mjs" status
pause
goto MENU

:DO_ATTACH
node.exe "D:\Documents\codex\agy plugins mannager\AGY-Launcher\cli.mjs" attach
pause
goto MENU

:DO_LAUNCH
node.exe "D:\Documents\codex\agy plugins mannager\AGY-Launcher\cli.mjs" launch
pause
goto MENU

:DO_STOP
node.exe "D:\Documents\codex\agy plugins mannager\AGY-Launcher\cli.mjs" stop
pause
goto MENU

:DO_SHORTCUT
node.exe "D:\Documents\codex\agy plugins mannager\AGY-Launcher\cli.mjs" shortcut
pause
goto MENU

:DO_DAEMON
node.exe "D:\Documents\codex\agy plugins mannager\AGY-Launcher\cli.mjs" daemon
pause
goto MENU

:DO_LOGS
if exist "D:\Documents\codex\agy plugins mannager\AGY-Launcher\logs\launcher.log" powershell.exe -NoProfile -Command "Get-Content -Path 'D:\Documents\codex\agy plugins mannager\AGY-Launcher\logs\launcher.log' -Tail 30 -Encoding UTF8"
if not exist "D:\Documents\codex\agy plugins mannager\AGY-Launcher\logs\launcher.log" echo 暂无日志文件。
pause
goto MENU

:DO_EXIT
exit /b 0
