@echo off
setlocal EnableExtensions
chcp 65001 >nul

for %%I in ("%~dp0\..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"
if not exist "data\runtime" mkdir "data\runtime" >nul 2>&1
set "VENV_PYTHON=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "SETUP_SCRIPT=%PROJECT_ROOT%\scripts\setup_windows.ps1"
set "SETUP_MARKER=%PROJECT_ROOT%\data\runtime\windows_setup_complete.json"
set "NO_PROXY=localhost,127.0.0.1,::1"
set "no_proxy=%NO_PROXY%"
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"

if not exist "%VENV_PYTHON%" (
    echo [启动检查] 首次运行，正在安装 Windows 依赖...
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SETUP_SCRIPT%"
    if errorlevel 1 goto :failed
)

"%VENV_PYTHON%" -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo [启动检查] 当前虚拟环境的 Tkinter 不可用，正在重建环境...
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SETUP_SCRIPT%" -Rebuild
    if errorlevel 1 goto :failed
)

"%VENV_PYTHON%" -c "import httpx, edge_tts; from PIL import Image" >nul 2>&1
if errorlevel 1 (
    echo [启动检查] 虚拟环境存在，但核心 Python 依赖不完整，正在修复...
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SETUP_SCRIPT%"
    if errorlevel 1 goto :failed
)

if not exist "%SETUP_MARKER%" (
    echo [启动检查] 旧环境没有完成标记，但 Python 和 GUI 核心依赖有效，直接启动。
)

echo Starting Novel Video Pipeline GUI...
echo Project: %PROJECT_ROOT%
"%VENV_PYTHON%" -m app.gui >> "%PROJECT_ROOT%\data\runtime\gui_launch.log" 2>&1
set "RESULT=%errorlevel%"
if not "%RESULT%"=="0" (
    echo.
    echo [ERROR] GUI 异常退出，错误码：%RESULT%
    echo 日志：%PROJECT_ROOT%\data\runtime\gui_launch.log
    pause
)
exit /b %RESULT%

:failed
echo.
echo [ERROR] Windows 运行环境初始化失败。
echo 请重新双击 Install_Windows_Dependencies.bat 查看详细错误。
pause
exit /b 1
