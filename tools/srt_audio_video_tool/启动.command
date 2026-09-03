#!/usr/bin/env bash
set -euo pipefail

TOOL_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT=""

if [ -f "$TOOL_DIR/project_path.txt" ]; then
  PROJECT_ROOT="$(sed -n '1p' "$TOOL_DIR/project_path.txt")"
fi

if [ ! -f "$PROJECT_ROOT/app/pipeline_runner.py" ]; then
  for CANDIDATE in "$HOME"/Desktop/novel_video_pipeline_mac_*; do
    if [ -f "$CANDIDATE/app/pipeline_runner.py" ]; then
      PROJECT_ROOT="$CANDIDATE"
      break
    fi
  done
fi

if [ ! -f "$PROJECT_ROOT/app/pipeline_runner.py" ]; then
  osascript -e 'display alert "找不到原小说视频项目" message "请确认原项目仍在桌面，或修改工具文件夹中的 project_path.txt。" as critical'
  exit 2
fi

if [ ! -x "$PROJECT_ROOT/.venv/bin/python" ]; then
  osascript -e 'display alert "原项目尚未安装运行环境" message "请先双击原项目里的 Open_GUI.command，完成依赖安装后再启动本工具。" as critical'
  exit 3
fi

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export PYTHONUNBUFFERED=1
export NOVEL_VIDEO_PROJECT_ROOT="$PROJECT_ROOT"
cd "$TOOL_DIR"
exec "$PROJECT_ROOT/.venv/bin/python" "$TOOL_DIR/srt_audio_video_gui.py" --project-root "$PROJECT_ROOT"
