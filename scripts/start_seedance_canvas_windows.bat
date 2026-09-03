@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0\.."
set "NO_PROXY=localhost,127.0.0.1,::1"
set "no_proxy=%NO_PROXY%"
set "PYTHONUTF8=1"

if not exist ".venv\Scripts\python.exe" (
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\setup_windows.ps1"
    if errorlevel 1 goto :failed
)

if not defined SEEDANCE_CANVAS_PORT set "SEEDANCE_CANVAS_PORT=7871"
start "" "http://127.0.0.1:%SEEDANCE_CANVAS_PORT%"
".venv\Scripts\python.exe" -m app.seedance_canvas serve --host 127.0.0.1 --port "%SEEDANCE_CANVAS_PORT%"
exit /b %errorlevel%

:failed
echo [ERROR] Windows 运行环境初始化失败。
pause
exit /b 1
