@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0scripts\start_seedance_canvas_windows.bat"
exit /b %errorlevel%
