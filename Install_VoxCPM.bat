@echo off
setlocal
cd /d "%~dp0"
title Novel Video Pipeline - VoxCPM2 Installer

if not exist ".venv\Scripts\python.exe" (
    echo [VoxCPM] Main application environment is missing. Initializing Windows dependencies...
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_windows.ps1"
    if errorlevel 1 goto :failed
)

echo [VoxCPM] Installing the official VoxCPM2 runtime...
".venv\Scripts\python.exe" -m pip install "voxcpm==2.0.3"
if errorlevel 1 goto :failed

".venv\Scripts\python.exe" -c "from voxcpm import VoxCPM; import torch; print('VoxCPM import OK'); print('PyTorch:', torch.__version__); print('CUDA available:', torch.cuda.is_available())"
if errorlevel 1 goto :failed

echo.
echo Installation complete. Select TTS Provider = voxcpm in the GUI.
echo The first synthesis downloads the openbmb/VoxCPM2 model (several GB).
pause
exit /b 0

:failed
echo.
echo [ERROR] VoxCPM installation or verification failed.
pause
exit /b 1
