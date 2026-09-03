#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ ! -x ".venv/bin/python" ]; then
  echo "[VoxCPM] 主程序环境不存在，先初始化主程序依赖..."
  scripts/setup_macos.sh
fi

echo "[VoxCPM] 安装官方 VoxCPM2 运行库（模型权重会在首次合成时下载）..."
.venv/bin/python -m pip install "voxcpm==2.0.3"
.venv/bin/python - <<'PY'
from voxcpm import VoxCPM
import torch
print("VoxCPM import OK")
print("PyTorch:", torch.__version__)
print("Apple MPS available:", torch.backends.mps.is_available())
PY

echo
echo "安装完成。请在 GUI 里选择 TTS Provider = voxcpm，再选择收藏音色。"
echo "首次真实合成会自动下载 openbmb/VoxCPM2（数 GB），请预留磁盘空间。"
read -r -p "按回车关闭..." _
