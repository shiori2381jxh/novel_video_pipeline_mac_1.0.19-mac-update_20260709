@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Novel Video Pipeline - VoxCPM2

if not exist ".venv\Scripts\python.exe" (
    echo [VoxCPM] 主程序环境不存在，先初始化 Windows 依赖...
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_windows.ps1"
    if errorlevel 1 goto :failed
)

echo [VoxCPM] 正在安装官方 VoxCPM2 运行库...
".venv\Scripts\python.exe" -m pip install "voxcpm==2.0.3"
if errorlevel 1 goto :failed

".venv\Scripts\python.exe" -c "from voxcpm import VoxCPM; import torch; print('VoxCPM import OK'); print('PyTorch:', torch.__version__); print('CUDA available:', torch.cuda.is_available())"
if errorlevel 1 goto :failed

echo.
echo 安装完成。请在 GUI 里选择 TTS Provider = voxcpm，再选择收藏音色。
echo 首次真实合成会下载 openbmb/VoxCPM2（数 GB），请预留磁盘空间。
pause
exit /b 0

:failed
echo.
echo [ERROR] VoxCPM 安装或检测失败。
pause
exit /b 1
