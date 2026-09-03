#!/bin/bash
# 双击此文件即可将当前程序安全发布到新 GitHub 账号。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="python3"
fi

ACCOUNT="shiori2381jxh"
SOURCE_REPO="https://github.com/shiori2381jxh/-.git"
RELEASE_REPO="shiori2381jxh/novel_video_pipeline_release"
RELEASE_REPO_URL="https://github.com/shiori2381jxh/novel_video_pipeline_release.git"
OUT_DIR="$ROOT/dist/github_release"
NOTES_FILE="$OUT_DIR/release_notes.md"

finish() {
  echo
  echo "按回车键关闭此窗口。"
  read -r
}
trap finish EXIT

cd "$ROOT"
echo "正在检查 GitHub 登录账号…"
LOGGED_IN="$(gh api user --jq '.login')"
if [[ "$LOGGED_IN" != "$ACCOUNT" ]]; then
  echo "当前 gh 登录账号是：$LOGGED_IN"
  echo "请先使用 $ACCOUNT 登录后再运行。"
  exit 1
fi

VERSION="$($PYTHON -c 'from app.version import VERSION; print(VERSION)')"
TAG="v$VERSION"
echo "正在生成 $VERSION 的干净发布包…"
mkdir -p "$OUT_DIR"
printf '%s\n' \
  "## $VERSION macOS 更新" \
  "" \
  "- 更新当前程序功能与体验。" \
  "- 安装包不包含 API 密钥、个人配置、项目、任务或浏览器登录数据。" > "$NOTES_FILE"

"$PYTHON" scripts/build_release_package.py \
  --output-dir "$OUT_DIR" \
  --repo "$RELEASE_REPO" \
  --notes-file "$NOTES_FILE"

ZIP_PATH="$(find "$OUT_DIR" -maxdepth 1 -type f -name 'novel_video_pipeline_mac_*.zip' -print -quit)"
MANIFEST="$OUT_DIR/latest.json"
STAGING_DIR="${ZIP_PATH%.zip}"
if [[ -z "$ZIP_PATH" || ! -f "$MANIFEST" || ! -d "$STAGING_DIR" ]]; then
  echo "发布包生成不完整，已停止。"
  exit 1
fi

echo "正在检查发布包隐私…"
"$PYTHON" - "$ZIP_PATH" <<'PY'
import json
import sys
import zipfile
from app.config import API_KEY_FIELDS

package = sys.argv[1]
api_hits, forbidden = [], []
with zipfile.ZipFile(package) as archive:
    for name in archive.namelist():
        lower = name.lower()
        if not name.endswith('/') and any(part in lower for part in (
            'data/jobs/', 'data/projects/', 'data/runtime/',
            'chrome_debug_profile', '.venv/', '.git/', '.ds_store',
        )):
            forbidden.append(name)
        if name.endswith('.json'):
            payload = json.loads(archive.read(name))
            if isinstance(payload, dict) and set(payload).intersection(API_KEY_FIELDS):
                api_hits.append(name)
if api_hits or forbidden:
    raise SystemExit(f'隐私检查失败：API JSON={api_hits}; 禁止文件={forbidden}')
print('隐私检查通过：未发现 API Key、个人项目、任务或浏览器数据。')
PY

SOURCE_WORK="$(mktemp -d "${TMPDIR:-/tmp}/novel_source.XXXXXX")"
RELEASE_WORK="$(mktemp -d "${TMPDIR:-/tmp}/novel_release.XXXXXX")"
trap 'rm -rf "$SOURCE_WORK" "$RELEASE_WORK"; finish' EXIT

echo "正在同步安全源码到新源码仓库…"
git clone "$SOURCE_REPO" "$SOURCE_WORK"
rsync -a --delete --exclude='.git' "$STAGING_DIR/" "$SOURCE_WORK/"
git -C "$SOURCE_WORK" config user.name "$ACCOUNT"
git -C "$SOURCE_WORK" config user.email "$ACCOUNT@users.noreply.github.com"
git -C "$SOURCE_WORK" add -A
if ! git -C "$SOURCE_WORK" diff --cached --quiet; then
  git -C "$SOURCE_WORK" commit -m "Release macOS pipeline $VERSION"
  git -C "$SOURCE_WORK" push origin HEAD:main
fi

if ! git ls-remote --exit-code --heads "$RELEASE_REPO_URL" main >/dev/null 2>&1; then
  echo "正在初始化更新发布仓库…"
  git -C "$RELEASE_WORK" init -b main
  git -C "$RELEASE_WORK" config user.name "$ACCOUNT"
  git -C "$RELEASE_WORK" config user.email "$ACCOUNT@users.noreply.github.com"
  printf '%s\n' '# Novel Video Pipeline Releases' > "$RELEASE_WORK/README.md"
  git -C "$RELEASE_WORK" add README.md
  git -C "$RELEASE_WORK" commit -m 'Initialize release repository'
  git -C "$RELEASE_WORK" remote add origin "$RELEASE_REPO_URL"
  git -C "$RELEASE_WORK" push -u origin main
fi

echo "正在上传 GitHub 更新包…"
if gh release view "$TAG" --repo "$RELEASE_REPO" >/dev/null 2>&1; then
  gh release upload "$TAG" "$ZIP_PATH" "$MANIFEST" --repo "$RELEASE_REPO" --clobber
  gh release edit "$TAG" --repo "$RELEASE_REPO" --title "Novel Video Pipeline $VERSION macOS Update" --notes-file "$NOTES_FILE" --latest
else
  gh release create "$TAG" "$ZIP_PATH" "$MANIFEST" \
    --repo "$RELEASE_REPO" \
    --target main \
    --title "Novel Video Pipeline $VERSION macOS Update" \
    --notes-file "$NOTES_FILE" \
    --latest
fi

echo
echo "发布完成：$TAG"
echo "更新清单：https://github.com/$RELEASE_REPO/releases/latest/download/latest.json"
