@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Novel Video Pipeline - Windows Dependencies

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_windows.ps1"
set "RESULT=%errorlevel%"
echo.
if "%RESULT%"=="0" (
    echo Windows 依赖安装完成。现在可以双击“启动.bat”。
) else (
    echo [ERROR] 安装失败，错误码：%RESULT%
)
pause
exit /b %RESULT%
