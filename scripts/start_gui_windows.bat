@echo off
setlocal EnableExtensions
chcp 65001 >nul

cd /d "%~dp0\.."
if not exist "data\runtime" mkdir "data\runtime" >nul 2>&1
set "NO_PROXY=localhost,127.0.0.1,::1"
set "no_proxy=%NO_PROXY%"
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"

if not exist ".venv\Scripts\python.exe" (
    echo [启动检查] 首次运行，正在安装 Windows 依赖...
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\setup_windows.ps1"
    if errorlevel 1 goto :failed
)

".venv\Scripts\python.exe" -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo [启动检查] 当前虚拟环境的 Tkinter 不可用，正在重建环境...
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\setup_windows.ps1" -Rebuild
    if errorlevel 1 goto :failed
)

echo Starting Novel Video Pipeline GUI...
echo Project: %CD%
".venv\Scripts\python.exe" -m app.gui >> "data\runtime\gui_launch.log" 2>&1
set "RESULT=%errorlevel%"
if not "%RESULT%"=="0" (
    echo.
    echo [ERROR] GUI 异常退出，错误码：%RESULT%
    echo 日志：%CD%\data\runtime\gui_launch.log
    pause
)
exit /b %RESULT%

:failed
echo.
echo [ERROR] Windows 运行环境初始化失败。
echo 请重新双击 Install_Windows_Dependencies.bat 查看详细错误。
pause
exit /b 1
